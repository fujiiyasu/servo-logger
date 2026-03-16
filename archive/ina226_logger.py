#!/usr/bin/env python3
"""
ina226_logger.py
================
INA226 電流・電圧センサ データロギングスクリプト

【配線】
  Raspberry Pi      INA226
  ─────────────────────────
  3.3V          →   VCC
  GND           →   GND
  GPIO2 (SDA)   →   SDA
  GPIO3 (SCL)   →   SCL
  ※ シャント抵抗を負荷の直列に挿入

【デフォルトI2Cアドレス】
  INA226: 0x40 (A0=GND, A1=GND)
  変更例: A0=VCC → 0x41, A1=VCC → 0x44

【使い方】
  python ina226_logger.py                       # コンソール表示
  python ina226_logger.py --output log.csv      # CSVファイルへ保存
  python ina226_logger.py --interval 0.5 --duration 60  # 0.5秒間隔で60秒
"""

import time
import csv
import sys
import struct
import argparse
from datetime import datetime
from smbus2 import SMBus

# ─── INA226 レジスタ定義 ─────────────────────────────────
INA226_ADDR            = 0x40   # デフォルトI2Cアドレス (変更可)

REG_CONFIG             = 0x00
REG_SHUNT_VOLTAGE      = 0x01
REG_BUS_VOLTAGE        = 0x02
REG_POWER              = 0x03
REG_CURRENT            = 0x04
REG_CALIBRATION        = 0x05
REG_MASK_ENABLE        = 0x06
REG_ALERT_LIMIT        = 0x07
REG_MANUFACTURER_ID    = 0xFE
REG_DIE_ID             = 0xFF

# Configuration レジスタ値
# AVG=16回平均, VBUS変換1.1ms, VSHUNT変換1.1ms, 連続測定
CONFIG_VALUE = (
    0x4000 |   # リセットなし
    0x0200 |   # AVG: 16回平均
    0x0140 |   # VBUS CT: 1.1ms
    0x00D8 |   # VSHUNT CT: 1.1ms
    0x0007     # Mode: 連続 (shunt + bus)
)

# キャリブレーション定数
# Cal = 0.00512 / (CURRENT_LSB * R_SHUNT)
# 例: R_SHUNT=0.1Ω, CURRENT_LSB=0.001A (1mA/bit) の場合
R_SHUNT_OHM    = 0.1     # シャント抵抗値 [Ω]
CURRENT_LSB_A  = 0.001   # 電流LSB [A/bit] = 最大電流 / 32768
CAL_VALUE      = int(0.00512 / (CURRENT_LSB_A * R_SHUNT_OHM))

# 電圧LSB
BUS_VOLTAGE_LSB    = 0.00125   # 1.25 mV/bit
SHUNT_VOLTAGE_LSB  = 0.0000025 # 2.5 μV/bit


class INA226:
    """INA226 電流・電圧センサ ドライバ"""

    def __init__(self, bus_num: int = 1, address: int = INA226_ADDR):
        self.bus     = SMBus(bus_num)
        self.address = address
        self._init_device()

    def _write_register(self, reg: int, value: int):
        """16bitレジスタに書き込む"""
        data = [(value >> 8) & 0xFF, value & 0xFF]
        self.bus.write_i2c_block_data(self.address, reg, data)

    def _read_register(self, reg: int) -> int:
        """16bit符号付きレジスタを読む"""
        data = self.bus.read_i2c_block_data(self.address, reg, 2)
        raw  = (data[0] << 8) | data[1]
        # 符号付き16bit変換
        if raw > 32767:
            raw -= 65536
        return raw

    def _read_register_unsigned(self, reg: int) -> int:
        """16bit符号なしレジスタを読む"""
        data = self.bus.read_i2c_block_data(self.address, reg, 2)
        return (data[0] << 8) | data[1]

    def _init_device(self):
        """デバイスを初期化・キャリブレーション"""
        # デバイスID確認
        mfr_id = self._read_register_unsigned(REG_MANUFACTURER_ID)
        die_id = self._read_register_unsigned(REG_DIE_ID)
        if mfr_id != 0x5449:
            print(f"  ⚠ 警告: メーカーID不一致 (0x{mfr_id:04X}, 期待値: 0x5449)")
        else:
            print(f"[OK] INA226 検出 (MFR: 0x{mfr_id:04X}, DIE: 0x{die_id:04X})")

        # 設定・キャリブレーション書き込み
        self._write_register(REG_CONFIG,      CONFIG_VALUE)
        self._write_register(REG_CALIBRATION, CAL_VALUE)
        print(f"[OK] INA226 初期化完了 (I2C: 0x{self.address:02X}, "
              f"Cal: {CAL_VALUE}, R_shunt: {R_SHUNT_OHM}Ω)")
        time.sleep(0.01)

    @property
    def bus_voltage_v(self) -> float:
        """バス電圧 [V]"""
        raw = self._read_register_unsigned(REG_BUS_VOLTAGE)
        return raw * BUS_VOLTAGE_LSB

    @property
    def shunt_voltage_mv(self) -> float:
        """シャント電圧 [mV]"""
        raw = self._read_register(REG_SHUNT_VOLTAGE)
        return raw * SHUNT_VOLTAGE_LSB * 1000  # V → mV

    @property
    def current_ma(self) -> float:
        """電流 [mA]"""
        raw = self._read_register(REG_CURRENT)
        return raw * CURRENT_LSB_A * 1000  # A → mA

    @property
    def power_mw(self) -> float:
        """電力 [mW]"""
        raw = self._read_register_unsigned(REG_POWER)
        return raw * (CURRENT_LSB_A * 25) * 1000  # W → mW

    def read_all(self) -> dict:
        """全測定値をまとめて読む"""
        return {
            "timestamp":       datetime.now().isoformat(timespec="milliseconds"),
            "bus_voltage_v":   round(self.bus_voltage_v,   4),
            "shunt_voltage_mv":round(self.shunt_voltage_mv,4),
            "current_ma":      round(self.current_ma,      3),
            "power_mw":        round(self.power_mw,        3),
        }

    def close(self):
        self.bus.close()


def log_to_console(sensor: INA226, interval: float, duration: float):
    """コンソールにリアルタイム表示"""
    print("\n  時刻                      電圧[V]   シャント[mV]  電流[mA]  電力[mW]")
    print("  " + "─" * 72)
    start = time.time()
    try:
        while True:
            if duration > 0 and (time.time() - start) >= duration:
                break
            d = sensor.read_all()
            print(f"  {d['timestamp']}  "
                  f"{d['bus_voltage_v']:7.4f}V  "
                  f"{d['shunt_voltage_mv']:8.4f}mV  "
                  f"{d['current_ma']:8.3f}mA  "
                  f"{d['power_mw']:8.3f}mW")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[割り込み] ロギング停止")


def log_to_csv(sensor: INA226, interval: float, duration: float, filepath: str):
    """CSVファイルにロギング"""
    fieldnames = ["timestamp", "bus_voltage_v", "shunt_voltage_mv",
                  "current_ma", "power_mw"]
    print(f"\n[CSV] {filepath} に書き込み開始...")
    start = time.time()
    count = 0
    try:
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            while True:
                if duration > 0 and (time.time() - start) >= duration:
                    break
                d = sensor.read_all()
                writer.writerow(d)
                f.flush()
                count += 1
                # コンソールにも表示
                print(f"  [{count:5d}] {d['timestamp']} | "
                      f"{d['bus_voltage_v']:.4f}V | "
                      f"{d['current_ma']:.1f}mA | "
                      f"{d['power_mw']:.1f}mW")
                time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n[割り込み] ロギング停止 ({count} サンプル記録)")
    print(f"[OK] 保存完了: {filepath} ({count} サンプル)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="INA226 電流・電圧ロガー")
    parser.add_argument("--address",  "-a", type=lambda x: int(x, 0),
                        default=INA226_ADDR, help=f"I2Cアドレス (default: 0x{INA226_ADDR:02X})")
    parser.add_argument("--bus",      "-b", type=int, default=1,
                        help="I2Cバス番号 (default: 1)")
    parser.add_argument("--interval", "-i", type=float, default=1.0,
                        help="サンプリング間隔 [秒] (default: 1.0)")
    parser.add_argument("--duration", "-d", type=float, default=0,
                        help="ロギング時間 [秒] 0=無制限 (default: 0)")
    parser.add_argument("--output",   "-o", type=str, default=None,
                        help="CSV出力ファイルパス (未指定=コンソールのみ)")
    parser.add_argument("--rshunt",   "-r", type=float, default=R_SHUNT_OHM,
                        help=f"シャント抵抗値 [Ω] (default: {R_SHUNT_OHM})")
    args = parser.parse_args()

    # シャント抵抗を変更する場合はグローバル更新
    R_SHUNT_OHM = args.rshunt
    CAL_VALUE   = int(0.00512 / (CURRENT_LSB_A * R_SHUNT_OHM))

    sensor = INA226(bus_num=args.bus, address=args.address)

    if args.output:
        log_to_csv(sensor, args.interval, args.duration, args.output)
    else:
        log_to_console(sensor, args.interval, args.duration)

    sensor.close()