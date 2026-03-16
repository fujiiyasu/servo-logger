#!/usr/bin/env python3
"""
servo_sweep.py
==============
PCA9685 シンプルスイープ (smbus2 直接制御)
adafruit ライブラリを使わず smbus2 でレジスタを直接操作します
"""

import time
import smbus2

# ─── 設定 ──────────────────────────────────────────────────
I2C_BUS     = 1
PCA_ADDR    = 0x41   # PCA9685 I2Cアドレス
SERVO_CH    = 0      # 使用するチャンネル (0〜15)

# PCA9685 レジスタ
MODE1       = 0x00
PRESCALE    = 0xFE
LED0_ON_L   = 0x06   # チャンネル0のベースレジスタ

# サーボ設定 (50Hz = 20ms周期)
PWM_FREQ_HZ = 50
SERVO_MIN   = 500    # 0度のパルス幅 [μs]
SERVO_MAX   = 2500   # 180度のパルス幅 [μs]


def set_pwm_freq(bus, freq_hz):
    """PWM周波数を設定する"""
    # prescale値を計算: 25MHz / (4096 * freq) - 1
    prescale = round(25_000_000 / (4096 * freq_hz)) - 1
    print(f"  prescale = {prescale}")

    # 現在のMODE1を読む
    old_mode = bus.read_byte_data(PCA_ADDR, MODE1)
    # スリープモードにして prescale を書く
    bus.write_byte_data(PCA_ADDR, MODE1, (old_mode & 0x7F) | 0x10)
    bus.write_byte_data(PCA_ADDR, PRESCALE, prescale)
    # スリープ解除
    bus.write_byte_data(PCA_ADDR, MODE1, old_mode)
    time.sleep(0.005)
    # RESTART ビットをセット
    bus.write_byte_data(PCA_ADDR, MODE1, old_mode | 0x80)
    print(f"  PWM周波数設定完了: {freq_hz}Hz")


def set_servo_angle(bus, channel, angle_deg):
    """サーボを指定角度に動かす"""
    # 角度 → パルス幅[μs] → PWMカウント値(0〜4095)に変換
    pulse_us  = SERVO_MIN + (SERVO_MAX - SERVO_MIN) * angle_deg / 180
    pulse_cnt = int(pulse_us / (1_000_000 / PWM_FREQ_HZ) * 4096)

    reg = LED0_ON_L + 4 * channel
    bus.write_byte_data(PCA_ADDR, reg,     0x00)         # ON_L
    bus.write_byte_data(PCA_ADDR, reg + 1, 0x00)         # ON_H
    bus.write_byte_data(PCA_ADDR, reg + 2, pulse_cnt & 0xFF)        # OFF_L
    bus.write_byte_data(PCA_ADDR, reg + 3, (pulse_cnt >> 8) & 0xFF) # OFF_H


def main():
    print("=== PCA9685 シンプルスイープ ===")
    bus = smbus2.SMBus(I2C_BUS)

    # 初期化: MODE1 をリセット
    bus.write_byte_data(PCA_ADDR, MODE1, 0x00)
    time.sleep(0.01)

    # PWM周波数設定
    set_pwm_freq(bus, PWM_FREQ_HZ)

    print(f"\nch{SERVO_CH} をスイープします (Ctrl+C で停止)\n")
    try:
        while True:
            # 0° → 180°
            for angle in range(0, 181, 2):
                set_servo_angle(bus, SERVO_CH, angle)
                print(f"  {angle:3d}°", end="\r")
                time.sleep(0.02)

            # 180° → 0°
            for angle in range(180, -1, -2):
                set_servo_angle(bus, SERVO_CH, angle)
                print(f"  {angle:3d}°", end="\r")
                time.sleep(0.02)

    except KeyboardInterrupt:
        print("\n\n停止します...")
        set_servo_angle(bus, SERVO_CH, 90)  # 中央に戻す
        time.sleep(0.5)

    finally:
        bus.close()
        print("完了")


if __name__ == "__main__":
    main()