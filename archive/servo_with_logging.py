#!/usr/bin/env python3
"""
pwm_measure_pigpio.py
=====================
PCA9685 PWM信号の高精度計測 (pigpio使用)
精度: ±1〜5μs

【事前準備】
  sudo apt-get install pigpio python3-pigpio
  sudo systemctl enable pigpiod
  sudo systemctl start pigpiod

【配線】
  PCA9685 ch0 信号ピン → 抵抗分圧回路 → GPIO17 (Pin11)
  ※ PCA9685 VCC=5Vの場合は必ず抵抗分圧すること
     1kΩ と 2.2kΩ で 5V → 約3.4V に降圧

【使い方】
  python3 pwm_measure_pigpio.py
  python3 pwm_measure_pigpio.py --output pwm_log.csv
  python3 pwm_measure_pigpio.py --pin 27 --output pwm_log.csv
"""

import time
import csv
import smbus2
import argparse
from datetime import datetime

try:
    import pigpio
except ImportError:
    print("pigpio が見つかりません。以下を実行してください:")
    print("  sudo apt-get install pigpio python3-pigpio")
    print("  sudo systemctl start pigpiod")
    exit(1)

# ─── 設定 ──────────────────────────────────────────────────
I2C_BUS     = 1
PCA_ADDR    = 0x41      # PCA9685 アドレス
SERVO_CH    = 0         # サーボチャンネル
MEASURE_PIN = 17        # 計測用 GPIO ピン番号 (BCM)

PWM_FREQ_HZ = 50
SERVO_MIN   = 500       # 0度 [μs]
SERVO_MAX   = 2500      # 180度 [μs]
SWEEP_STEP  = 5         # スイープステップ [度]
SWEEP_DELAY = 0.15      # ステップ間待ち [秒]

# PCA9685 レジスタ
PCA_MODE1    = 0x00
PCA_PRESCALE = 0xFE
PCA_LED0_L   = 0x06


# ─── PCA9685 制御 ───────────────────────────────────────────
def pca_init(bus):
    bus.write_byte_data(PCA_ADDR, PCA_MODE1, 0x00)
    time.sleep(0.01)
    prescale = round(25_000_000 / (4096 * PWM_FREQ_HZ)) - 1
    old_mode = bus.read_byte_data(PCA_ADDR, PCA_MODE1)
    bus.write_byte_data(PCA_ADDR, PCA_MODE1, (old_mode & 0x7F) | 0x10)
    bus.write_byte_data(PCA_ADDR, PCA_PRESCALE, prescale)
    bus.write_byte_data(PCA_ADDR, PCA_MODE1, old_mode)
    time.sleep(0.005)
    bus.write_byte_data(PCA_ADDR, PCA_MODE1, old_mode | 0x80)
    print(f"[OK] PCA9685 初期化完了 (addr=0x{PCA_ADDR:02X})")


def pca_set_angle(bus, channel, angle_deg):
    pulse_us  = SERVO_MIN + (SERVO_MAX - SERVO_MIN) * angle_deg / 180
    pulse_cnt = int(pulse_us / (1_000_000 / PWM_FREQ_HZ) * 4096)
    reg = PCA_LED0_L + 4 * channel
    bus.write_byte_data(PCA_ADDR, reg,     0x00)
    bus.write_byte_data(PCA_ADDR, reg + 1, 0x00)
    bus.write_byte_data(PCA_ADDR, reg + 2, pulse_cnt & 0xFF)
    bus.write_byte_data(PCA_ADDR, reg + 3, (pulse_cnt >> 8) & 0xFF)
    return pulse_us  # 設定パルス幅を返す


# ─── pigpio PWM 計測クラス ──────────────────────────────────
class PulseWidthMeter:
    """pigpio のエッジ検出コールバックで高精度にパルス幅を計測する"""

    def __init__(self, pi, pin):
        self.pi      = pi
        self.pin     = pin
        self._rise   = None   # 立ち上がり時刻 [μs]
        self._pulse  = None   # 最新のパルス幅 [μs]
        self._period = None   # 最新の周期 [μs]
        self._prev_rise = None

        pi.set_mode(pin, pigpio.INPUT)
        self._cb = pi.callback(pin, pigpio.EITHER_EDGE, self._edge_callback)

    def _edge_callback(self, gpio, level, tick):
        """エッジ検出コールバック (pigpiod が μs 精度で呼び出す)"""
        if level == pigpio.HIGH:
            # 立ち上がり: 周期を計算
            if self._prev_rise is not None:
                self._period = pigpio.tickDiff(self._prev_rise, tick)
            self._prev_rise = tick
            self._rise = tick
        elif level == pigpio.LOW:
            # 立ち下がり: パルス幅を計算
            if self._rise is not None:
                self._pulse = pigpio.tickDiff(self._rise, tick)

    def read(self):
        """
        最新の計測値を返す
        Returns:
            pulse_us   : パルス幅 [μs]
            period_us  : 周期 [μs]
            duty       : デューティ比 [%]
            freq_hz    : 周波数 [Hz]
        """
        pulse  = self._pulse
        period = self._period
        if pulse is None or period is None or period == 0:
            return None, None, None, None
        duty    = pulse / period * 100
        freq_hz = 1_000_000 / period
        return pulse, period, duty, freq_hz

    def cancel(self):
        self._cb.cancel()


# ─── メイン ────────────────────────────────────────────────
def main(output_csv, pin):
    print("=== PWM 高精度計測 (pigpio) ===")
    print(f"  計測ピン: GPIO{pin}  サーボ ch{SERVO_CH}")
    print(f"  PCA9685: 0x{PCA_ADDR:02X}  精度: ±1〜5μs")
    if output_csv:
        print(f"  CSV出力: {output_csv}")
    print("  Ctrl+C で停止\n")

    # pigpiod に接続
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpiod に接続できません。以下を実行してください:")
        print("  sudo systemctl start pigpiod")
        exit(1)
    print("[OK] pigpiod 接続完了")

    # I2C / PCA9685 初期化
    bus = smbus2.SMBus(I2C_BUS)
    pca_init(bus)

    # 計測器初期化
    meter = PulseWidthMeter(pi, pin)
    time.sleep(0.1)  # コールバック安定待ち

    log_data = []

    print(f"\n  {'時刻':<26} {'角度':>4} {'設定':>8} {'計測':>8} {'周期':>8} {'デューティ':>8} {'周波数':>8}")
    print("  " + "─" * 82)

    try:
        while True:
            angles = list(range(0, 181, SWEEP_STEP)) + list(range(180, -1, -SWEEP_STEP))
            for angle in angles:
                expected_us = pca_set_angle(bus, SERVO_CH, angle)
                time.sleep(SWEEP_DELAY)

                pulse, period, duty, freq = meter.read()
                ts = datetime.now().isoformat(timespec="milliseconds")

                if pulse is not None:
                    print(f"  {ts}  {angle:3d}°  "
                          f"{expected_us:7.1f}μs  "
                          f"{pulse:7.1f}μs  "
                          f"{period:7.1f}μs  "
                          f"{duty:6.2f}%  "
                          f"{freq:6.2f}Hz", end="\r")
                    row = {
                        "timestamp":    ts,
                        "angle_deg":    angle,
                        "expected_us":  round(expected_us, 1),
                        "measured_us":  round(pulse, 1),
                        "period_us":    round(period, 1),
                        "duty_percent": round(duty, 3),
                        "freq_hz":      round(freq, 3),
                    }
                else:
                    print(f"  {ts}  {angle:3d}°  計測待ち...", end="\r")
                    row = {
                        "timestamp":    ts,
                        "angle_deg":    angle,
                        "expected_us":  round(expected_us, 1),
                        "measured_us":  None,
                        "period_us":    None,
                        "duty_percent": None,
                        "freq_hz":      None,
                    }
                log_data.append(row)

    except KeyboardInterrupt:
        print(f"\n\n停止します... ({len(log_data)} サンプル収集)")
        pca_set_angle(bus, SERVO_CH, 90)
        time.sleep(0.3)

    finally:
        meter.cancel()
        pi.stop()
        bus.close()

        if output_csv and log_data:
            with open(output_csv, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(log_data[0].keys()))
                writer.writeheader()
                writer.writerows(log_data)
            print(f"[OK] CSV保存: {output_csv} ({len(log_data)} 件)")

        print("完了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PWM 高精度計測 (pigpio)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="CSV出力ファイルパス")
    parser.add_argument("--pin",    "-p", type=int, default=MEASURE_PIN,
                        help=f"計測GPIO番号 BCM (default: {MEASURE_PIN})")
    args = parser.parse_args()
    main(args.output, args.pin)