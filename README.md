# Servo Logger

Raspberry Pi + マイコン + PCA9685 を使ったサーボ制御・PWMパルス幅計測システムです。

---

## リポジトリ構成

```
servo-logger/
├── raspi/              # Raspberry Pi 側（Flask Webサーバー）
├── firmware/
│   ├── openrb/         # OpenRB-150 用スケッチ（PlatformIO）
│   └── m5stack/        # M5Stack 用スケッチ（PlatformIO）
└── README.md           # このファイル
```

---

## システム構成

### OpenRB-150 版
```
ブラウザ → Raspberry Pi (Flask) → OpenRB-150 → PCA9685 → サーボ x3
```

### M5Stack 版
```
ブラウザ → Raspberry Pi (Flask) → M5Stack → PCA9685 → サーボ x3
```

---

## 各ディレクトリの詳細

- **[raspi/](raspi/README.md)** — Raspberry Pi 側のセットアップ・使い方
- **[firmware/openrb/](firmware/openrb/)** — OpenRB-150 用 PlatformIO プロジェクト
- **[firmware/m5stack/](firmware/m5stack/)** — M5Stack 用 PlatformIO プロジェクト

---

## 主な機能

- サーボ3ch リアルタイム制御（Web UI）
- PWM パルス幅計測・リアルタイムグラフ表示
- 自動スイープ（往復運動）
- CSV データ保存・ダウンロード
- タイムラプス撮影
- セッション再生ビューア