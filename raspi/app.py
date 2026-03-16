#!/usr/bin/env python3
"""
app.py - Flask + SocketIO サーボ3ch制御 + シリアルロガー + カメラ
"""

import csv
import io
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import serial
import smbus2
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory
from flask_socketio import SocketIO

from camera import TimelapseCamera

# ─── 設定 ──────────────────────────────────────────────────
SERIAL_PORT  = "/dev/ttyACM0"
BAUD_RATE    = 115200
I2C_BUS      = 1
PCA_ADDR     = 0x41
PWM_FREQ_HZ  = 50
SERVO_MIN    = 500
SERVO_MAX    = 2500
PULSE_MIN    = 500
PULSE_MAX    = 2500
LOG_DIR      = Path.home() / "servo_project" / "logs"
CAMERA_DEV   = 0
CAPTURE_INTERVAL = 60.0

# サーボチャンネル設定 (PCA9685チャンネル番号)
SERVO_CHANNELS = [0, 1, 2]

PCA_MODE1    = 0x00
PCA_PRESCALE = 0xFE
PCA_LED0_L   = 0x06

# ─── アプリ初期化 ───────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'servo_logger_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ─── 状態 ──────────────────────────────────────────────────
state = {
    # チャンネルごとの状態
    "servo_enabled": [False, False, False],
    "current_angle": [90, 90, 90],
    # 計測
    "measuring":     False,
    "data":          [],
    "bus":           None,
    # セッション
    "session_dir":   None,
    "session_name":  None,
    "start_time":    None,
    # スイープ
    "sweep_active":  [False, False, False],
    "sweep_period":  [2.0, 2.0, 2.0],
}
state_lock   = threading.Lock()
serial_write_queue = queue.Queue()
ser          = None
camera       = None
sweep_threads = [None, None, None]


# ─── PCA9685 ───────────────────────────────────────────────
def pca_init():
    try:
        bus = smbus2.SMBus(I2C_BUS)
        bus.write_byte_data(PCA_ADDR, PCA_MODE1, 0x00)
        time.sleep(0.01)
        prescale = round(25_000_000 / (4096 * PWM_FREQ_HZ)) - 1
        old_mode = bus.read_byte_data(PCA_ADDR, PCA_MODE1)
        bus.write_byte_data(PCA_ADDR, PCA_MODE1, (old_mode & 0x7F) | 0x10)
        bus.write_byte_data(PCA_ADDR, PCA_PRESCALE, prescale)
        bus.write_byte_data(PCA_ADDR, PCA_MODE1, old_mode)
        time.sleep(0.005)
        bus.write_byte_data(PCA_ADDR, PCA_MODE1, old_mode | 0x80)
        state["bus"] = bus
        print("[OK] PCA9685 初期化完了")
        return True
    except Exception as e:
        print(f"[ERROR] PCA9685: {e}")
        return False


def pca_set_angle(ch, angle_deg):
    if not state["bus"] or not state["servo_enabled"][ch]:
        return
    pulse_us  = SERVO_MIN + (SERVO_MAX - SERVO_MIN) * angle_deg / 180
    pulse_cnt = int(pulse_us / (1_000_000 / PWM_FREQ_HZ) * 4096)
    reg = PCA_LED0_L + 4 * SERVO_CHANNELS[ch]
    bus = state["bus"]
    bus.write_byte_data(PCA_ADDR, reg,     0x00)
    bus.write_byte_data(PCA_ADDR, reg + 1, 0x00)
    bus.write_byte_data(PCA_ADDR, reg + 2, pulse_cnt & 0xFF)
    bus.write_byte_data(PCA_ADDR, reg + 3, (pulse_cnt >> 8) & 0xFF)


def pca_stop_ch(ch):
    if not state["bus"]:
        return
    reg = PCA_LED0_L + 4 * SERVO_CHANNELS[ch]
    for i in range(4):
        state["bus"].write_byte_data(PCA_ADDR, reg + i, 0x00)


# ─── セッション管理 ─────────────────────────────────────────
def create_session():
    name = datetime.now().strftime("session_%Y%m%d_%H%M%S")
    path = LOG_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    state["session_dir"]  = path
    state["session_name"] = name
    state["data"]         = []
    state["start_time"]   = time.time()
    print(f"[OK] セッション作成: {path}")
    return path


def save_session_files():
    path = state["session_dir"]
    if not path:
        return
    data = state["data"]
    if data:
        csv_path = path / "data.csv"
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        print(f"[OK] CSV保存: {csv_path} ({len(data)} 件)")
    if camera and camera.frame_log:
        with open(path / "frames.json", 'w') as f:
            json.dump(camera.frame_log, f)
        print(f"[OK] フレームログ保存: {len(camera.frame_log)} フレーム")


# ─── 自動スイープ ────────────────────────────────────────────
def sweep_loop(ch):
    while state["sweep_active"][ch]:
        period = state["sweep_period"][ch]
        steps  = 100
        delay  = period / steps

        for i in range(steps + 1):
            if not state["sweep_active"][ch]:
                return
            angle = i * 180 / steps
            state["current_angle"][ch] = angle
            pca_set_angle(ch, angle)
            socketio.emit('sweep_angle', {"ch": ch, "angle": round(angle, 1)})
            time.sleep(delay)

        for i in range(steps + 1):
            if not state["sweep_active"][ch]:
                return
            angle = 180 - i * 180 / steps
            state["current_angle"][ch] = angle
            pca_set_angle(ch, angle)
            socketio.emit('sweep_angle', {"ch": ch, "angle": round(angle, 1)})
            time.sleep(delay)


# ─── シリアル書き込みスレッド ────────────────────────────────
def serial_write_loop():
    global ser
    while True:
        try:
            cmd = serial_write_queue.get(timeout=0.1)
            if ser and ser.is_open:
                ser.write(cmd)
                ser.flush()
        except queue.Empty:
            pass


# ─── シリアル読み込みスレッド ────────────────────────────────
def serial_read_loop():
    global ser
    last_emit = 0
    EMIT_INTERVAL = 0.05

    while True:
        if not ser or not ser.is_open:
            time.sleep(0.1)
            continue
        try:
            line = ser.readline()
            if not line:
                continue
            line = line.decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            if line.startswith('#'):
                socketio.emit('log', {'message': line})
                continue

            # フォーマット: timestamp_ms,pulse_ch0,pulse_ch1,pulse_ch2
            parts = line.split(',')
            if len(parts) != 4:
                continue

            try:
                timestamp_ms = int(parts[0])
                pulses = [int(parts[1]), int(parts[2]), int(parts[3])]
            except ValueError:
                continue

            angles = []
            for p in pulses:
                a = round((p - PULSE_MIN) / (PULSE_MAX - PULSE_MIN) * 180, 1)
                angles.append(max(0.0, min(180.0, a)))

            recv_time = datetime.now().isoformat(timespec="milliseconds")

            with state_lock:
                if state["measuring"]:
                    state["data"].append({
                        "recv_time":    recv_time,
                        "timestamp_ms": timestamp_ms,
                        "pulse_ch0":    pulses[0],
                        "pulse_ch1":    pulses[1],
                        "pulse_ch2":    pulses[2],
                        "angle_ch0":    angles[0],
                        "angle_ch1":    angles[1],
                        "angle_ch2":    angles[2],
                    })

            now = time.time()
            if now - last_emit >= EMIT_INTERVAL:
                last_emit = now
                socketio.emit('data', {
                    "t":      timestamp_ms,
                    "pulses": pulses,
                    "angles": angles,
                })

        except serial.SerialException:
            print("[ERROR] シリアル切断")
            socketio.emit('log', {'message': '# シリアル切断'})
            ser = None
            time.sleep(1)
        except Exception:
            continue


# ─── Flask ルート ───────────────────────────────────────────
@app.route('/')
def index():
    return render_template("index.html")


@app.route('/api/status')
def api_status():
    return jsonify({
        "servo_enabled":    state["servo_enabled"],
        "current_angle":    state["current_angle"],
        "measuring":        state["measuring"],
        "sample_count":     len(state["data"]),
        "serial_connected": ser is not None,
        "session_name":     state["session_name"],
        "frame_count":      camera.frame_count if camera else 0,
        "sweep_active":     state["sweep_active"],
        "sweep_period":     state["sweep_period"],
    })


# ─── サーボ制御 ─────────────────────────────────────────────
@app.route('/api/servo/<int:ch>/on', methods=['POST'])
def servo_on(ch):
    if ch not in range(3):
        return jsonify({"error": "invalid ch"}), 400
    state["servo_enabled"][ch] = True
    pca_set_angle(ch, state["current_angle"][ch])
    return jsonify({"status": "ok", "ch": ch, "servo_enabled": True})


@app.route('/api/servo/<int:ch>/off', methods=['POST'])
def servo_off(ch):
    if ch not in range(3):
        return jsonify({"error": "invalid ch"}), 400
    state["servo_enabled"][ch] = False
    state["sweep_active"][ch]  = False
    pca_stop_ch(ch)
    return jsonify({"status": "ok", "ch": ch, "servo_enabled": False})


@app.route('/api/servo/all/on', methods=['POST'])
def servo_all_on():
    for ch in range(3):
        state["servo_enabled"][ch] = True
        pca_set_angle(ch, state["current_angle"][ch])
    return jsonify({"status": "ok", "servo_enabled": [True, True, True]})


@app.route('/api/servo/all/off', methods=['POST'])
def servo_all_off():
    for ch in range(3):
        state["servo_enabled"][ch] = False
        state["sweep_active"][ch]  = False
        pca_stop_ch(ch)
    return jsonify({"status": "ok", "servo_enabled": [False, False, False]})


@app.route('/api/servo/<int:ch>/angle/<int:angle>', methods=['POST'])
def servo_angle(ch, angle):
    if ch not in range(3):
        return jsonify({"error": "invalid ch"}), 400
    angle = max(0, min(180, angle))
    state["current_angle"][ch] = angle
    pca_set_angle(ch, angle)
    return jsonify({"status": "ok", "ch": ch, "angle": angle})


# ─── スイープ制御 ────────────────────────────────────────────
@app.route('/api/sweep/<int:ch>/start', methods=['POST'])
def sweep_start(ch):
    global sweep_threads
    if ch not in range(3):
        return jsonify({"error": "invalid ch"}), 400
    data   = request.get_json(silent=True) or {}
    period = max(1.0, float(data.get("period", 2.0)))
    state["sweep_period"][ch]  = period
    state["servo_enabled"][ch] = True
    state["sweep_active"][ch]  = True
    sweep_threads[ch] = threading.Thread(target=sweep_loop, args=(ch,), daemon=True)
    sweep_threads[ch].start()
    return jsonify({"status": "ok", "ch": ch, "period": period})


@app.route('/api/sweep/<int:ch>/stop', methods=['POST'])
def sweep_stop(ch):
    if ch not in range(3):
        return jsonify({"error": "invalid ch"}), 400
    state["sweep_active"][ch] = False
    return jsonify({"status": "ok", "ch": ch})


@app.route('/api/sweep/all/start', methods=['POST'])
def sweep_all_start():
    global sweep_threads
    data   = request.get_json(silent=True) or {}
    period = max(1.0, float(data.get("period", 2.0)))
    for ch in range(3):
        state["sweep_period"][ch]  = period
        state["servo_enabled"][ch] = True
        state["sweep_active"][ch]  = True
        sweep_threads[ch] = threading.Thread(target=sweep_loop, args=(ch,), daemon=True)
        sweep_threads[ch].start()
    return jsonify({"status": "ok", "period": period})


@app.route('/api/sweep/all/stop', methods=['POST'])
def sweep_all_stop():
    for ch in range(3):
        state["sweep_active"][ch] = False
    return jsonify({"status": "ok"})


# ─── 計測制御 ────────────────────────────────────────────────
@app.route('/api/measure/start', methods=['POST'])
def measure_start():
    session_dir = create_session()
    if ser and ser.is_open:
        ser.write(b's')
        ser.flush()
    with state_lock:
        state["measuring"] = True
    if camera:
        camera.session_dir = session_dir
        camera.start(state["start_time"])
    socketio.emit('log', {'message': f'# セッション開始: {state["session_name"]}'})
    return jsonify({"status": "ok", "session": state["session_name"]})


@app.route('/api/measure/stop', methods=['POST'])
def measure_stop():
    if ser and ser.is_open:
        ser.write(b'p')
        ser.flush()
    with state_lock:
        state["measuring"] = False
    if camera:
        camera.stop()
    save_session_files()
    return jsonify({
        "status":       "ok",
        "sample_count": len(state["data"]),
        "session":      state["session_name"],
    })


@app.route('/api/measure/reset', methods=['POST'])
def measure_reset():
    if ser and ser.is_open:
        ser.write(b'r')
        ser.flush()
    with state_lock:
        state["measuring"] = False
        state["data"].clear()
    if camera:
        camera.stop()
        camera.frame_log   = []
        camera.frame_count = 0
    return jsonify({"status": "ok"})


@app.route('/api/download/csv')
def download_csv():
    with state_lock:
        data = list(state["data"])
    if not data:
        return jsonify({"error": "データがありません"}), 404
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    output.seek(0)
    filename = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─── セッション・リプレイ ────────────────────────────────────
@app.route('/api/sessions')
def list_sessions():
    sessions = []
    if LOG_DIR.exists():
        for d in sorted(LOG_DIR.iterdir(), reverse=True):
            if d.is_dir() and (d / "data.csv").exists():
                frame_count = 0
                if (d / "frames.json").exists():
                    with open(d / "frames.json") as f:
                        frame_count = len(json.load(f))
                sessions.append({
                    "name":        d.name,
                    "frame_count": frame_count,
                    "has_data":    True,
                })
    return jsonify(sessions)


@app.route('/api/session/<session_name>/data')
def session_data(session_name):
    csv_path = LOG_DIR / session_name / "data.csv"
    if not csv_path.exists():
        return jsonify({"error": "データなし"}), 404
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            rows.append({
                "timestamp_ms": int(row["timestamp_ms"]),
                "pulse_ch0":    int(row["pulse_ch0"]),
                "pulse_ch1":    int(row["pulse_ch1"]),
                "pulse_ch2":    int(row["pulse_ch2"]),
                "angle_ch0":    float(row["angle_ch0"]),
                "angle_ch1":    float(row["angle_ch1"]),
                "angle_ch2":    float(row["angle_ch2"]),
            })
    return jsonify(rows)


@app.route('/api/session/<session_name>/frames')
def session_frames(session_name):
    frame_path = LOG_DIR / session_name / "frames.json"
    if not frame_path.exists():
        return jsonify([])
    with open(frame_path) as f:
        return jsonify(json.load(f))


@app.route('/session/<session_name>/image/<filename>')
def session_image(session_name, filename):
    return send_from_directory(LOG_DIR / session_name, filename)


@app.route('/replay')
def replay():
    return render_template("replay.html")


# ─── 起動 ──────────────────────────────────────────────────
def startup():
    global ser, camera
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pca_init()
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"[OK] シリアル接続: {SERIAL_PORT} ({BAUD_RATE}bps)")
    except serial.SerialException as e:
        print(f"[WARN] シリアル接続失敗: {e}")
    camera = TimelapseCamera(
        session_dir=LOG_DIR,
        interval_sec=CAPTURE_INTERVAL,
        device=CAMERA_DEV,
    )
    camera.open()
    threading.Thread(target=serial_read_loop,  daemon=True).start()
    threading.Thread(target=serial_write_loop, daemon=True).start()
    print("[OK] 起動完了")


if __name__ == '__main__':
    startup()
    print("[OK] サーバー起動: http://0.0.0.0:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)