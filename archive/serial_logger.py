#!/usr/bin/env python3
"""
serial_logger.py
================
OpenRB-150 からシリアルでADCデータを受信し、
CSVに保存 + コンソールにリアルタイム表示する

【使い方】
  python3 serial_logger.py                        # 手動で s/p コマンド
  python3 serial_logger.py --start                # 起動時に自動で計測開始
  python3 serial_logger.py --output my_log.csv    # 出力ファイル名を指定

【コマンド（実行中に入力）】
  s + Enter → 計測開始
  p + Enter → 計測停止
  r + Enter → リセット
  q + Enter → 終了してCSV保存
"""

import serial
import csv
import sys
import threading
import argparse
from datetime import datetime
from pathlib import Path

# ─── 設定 ──────────────────────────────────────────────────
SERIAL_PORT     = "/dev/ttyACM0"
BAUD_RATE       = 9600
ADC_MAX         = 4095       # OpenRB-150 は 12bit ADC
ADC_REF_VOLT    = 3.3        # 基準電圧 [V]
OUTPUT_DIR      = Path.home() / "servo_project" / "logs"


class SerialLogger:
    def __init__(self, port, baud, output_csv):
        self.port       = port
        self.baud       = baud
        self.output_csv = output_csv
        self.data       = []         # 受信データバッファ
        self.running    = False      # 受信スレッド動作フラグ
        self.measuring  = False      # 計測中フラグ
        self._ser       = None
        self._thread    = None

    def connect(self):
        """シリアルポートに接続"""
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1)
            print(f"[OK] シリアル接続: {self.port} ({self.baud}bps)")
            return True
        except serial.SerialException as e:
            print(f"[ERROR] シリアル接続失敗: {e}")
            return False

    def send_command(self, cmd):
        """OpenRB にコマンドを送信"""
        if self._ser and self._ser.is_open:
            self._ser.write(cmd.encode())
            print(f"[CMD] '{cmd}' を送信")

    def start_measuring(self):
        self.send_command('s')
        self.measuring = True

    def stop_measuring(self):
        self.send_command('p')
        self.measuring = False

    def reset(self):
        self.send_command('r')
        self.data.clear()
        print("[INFO] データをリセットしました")

    def _receive_loop(self):
        """バックグラウンドでシリアルデータを受信するスレッド"""
        while self.running:
            try:
                line = self._ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue

                # コメント行 (# で始まる) はそのまま表示
                if line.startswith('#'):
                    print(f"\n  {line}")
                    continue

                # データ行をパース: "timestamp_ms,adc_value"
                parts = line.split(',')
                if len(parts) != 2:
                    continue

                timestamp_ms = int(parts[0])
                adc_value    = int(parts[1])
                voltage      = adc_value / ADC_MAX * ADC_REF_VOLT
                recv_time    = datetime.now().isoformat(timespec="milliseconds")

                row = {
                    "recv_time":    recv_time,
                    "timestamp_ms": timestamp_ms,
                    "adc_value":    adc_value,
                    "voltage_v":    round(voltage, 4),
                }
                self.data.append(row)

                # コンソール表示
                print(f"  [{len(self.data):5d}] "
                      f"t={timestamp_ms:7d}ms  "
                      f"ADC={adc_value:4d}  "
                      f"V={voltage:.4f}V", end="\r")

            except (ValueError, UnicodeDecodeError):
                continue
            except serial.SerialException:
                print("\n[ERROR] シリアル切断")
                break

    def start(self):
        """受信スレッド開始"""
        self.running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """受信スレッド停止"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def save_csv(self):
        """収集データをCSVに保存"""
        if not self.data:
            print("\n[WARN] 保存するデータがありません")
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / self.output_csv

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(self.data[0].keys()))
            writer.writeheader()
            writer.writerows(self.data)

        print(f"\n[OK] CSV保存: {filepath} ({len(self.data)} サンプル)")

    def close(self):
        self.stop_measuring()
        self.stop()
        if self._ser and self._ser.is_open:
            self._ser.close()
        print("[OK] シリアル切断")


def interactive_loop(logger):
    """キーボード入力でコマンドを送るインタラクティブループ"""
    print("\n操作コマンド: s=開始  p=停止  r=リセット  q=終了&保存\n")
    while True:
        try:
            cmd = input("").strip().lower()
            if cmd == 's':
                logger.start_measuring()
            elif cmd == 'p':
                logger.stop_measuring()
                print(f"\n  収集サンプル数: {len(logger.data)}")
            elif cmd == 'r':
                logger.reset()
            elif cmd == 'q':
                logger.stop_measuring()
                break
            else:
                print("  不明なコマンドです (s/p/r/q)")
        except (KeyboardInterrupt, EOFError):
            break


def main():
    parser = argparse.ArgumentParser(description="OpenRB シリアルロガー")
    parser.add_argument("--port",   default=SERIAL_PORT,
                        help=f"シリアルポート (default: {SERIAL_PORT})")
    parser.add_argument("--baud",   type=int, default=BAUD_RATE,
                        help=f"ボーレート (default: {BAUD_RATE})")
    parser.add_argument("--output", default=f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        help="CSV出力ファイル名")
    parser.add_argument("--start",  action="store_true",
                        help="起動時に自動で計測開始")
    args = parser.parse_args()

    print("=== OpenRB シリアルロガー ===")
    print(f"  ポート: {args.port}  ボーレート: {args.baud}")
    print(f"  出力先: {OUTPUT_DIR / args.output}")

    logger = SerialLogger(args.port, args.baud, args.output)

    if not logger.connect():
        sys.exit(1)

    logger.start()

    # OpenRB の起動メッセージ待ち
    import time
    time.sleep(1.0)

    if args.start:
        logger.start_measuring()

    try:
        interactive_loop(logger)
    finally:
        logger.save_csv()
        logger.close()


if __name__ == "__main__":
    main()