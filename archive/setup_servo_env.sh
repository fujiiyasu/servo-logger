#!/bin/bash
# ============================================================
# Raspberry Pi セットアップスクリプト
# PCA9685 サーボコントローラ + INA226 電圧モニタ環境構築
# ============================================================

set -e

echo "========================================"
echo " PCA9685 + INA226 環境セットアップ開始"
echo "========================================"

# --- 1. I2C の有効化確認 ---
echo ""
echo "[1/6] I2C インターフェース確認..."
if ! lsmod | grep -q "i2c_bcm2835\|i2c_bcm2708"; then
    echo "  ⚠ I2C が有効になっていません。"
    echo "  以下のコマンドを実行して有効化してください:"
    echo "    sudo raspi-config  →  Interface Options → I2C → Enable"
    echo "  または:"
    echo "    sudo raspi-config nonint do_i2c 0"
    echo "  有効化後、再起動してこのスクリプトを再実行してください。"
    exit 1
else
    echo "  ✓ I2C は有効です"
fi

# --- 2. システムパッケージの更新とI2Cツール導入 ---
echo ""
echo "[2/6] システムパッケージ更新 & I2Cツール導入..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    i2c-tools \
    python3-smbus2
echo "  ✓ システムパッケージ導入完了"

# --- 3. Python 仮想環境の作成 ---
VENV_DIR="$HOME/servo_env"
echo ""
echo "[3/6] Python 仮想環境を作成: $VENV_DIR"
if [ -d "$VENV_DIR" ]; then
    echo "  ⚠ 既存の仮想環境を検出。削除して再作成します..."
    rm -rf "$VENV_DIR"
fi
python3 -m venv "$VENV_DIR"
echo "  ✓ 仮想環境作成完了"

# --- 4. 仮想環境に必要ライブラリをインストール ---
echo ""
echo "[4/6] 必要な Python ライブラリをインストール..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install \
    adafruit-circuitpython-pca9685 \
    adafruit-circuitpython-servokit \
    adafruit-blinka \
    smbus2 \
    RPi.GPIO

echo "  ✓ ライブラリインストール完了"
echo ""
echo "  インストール済みパッケージ:"
"$VENV_DIR/bin/pip" list | grep -E "adafruit|smbus|RPi"

# --- 5. I2C デバイスのスキャン ---
echo ""
echo "[5/6] I2C バスのスキャン..."
echo "  (PCA9685: 0x70 (hex) = 112dec, INA226: 0x40 (hex) = 64dec)"
i2cdetect -y 1 || echo "  ⚠ i2cdetect に失敗しました (root権限が必要な場合: sudo i2cdetect -y 1)"

# --- 6. サンプルスクリプトの配置 ---
echo ""
echo "[6/6] サンプルスクリプトを配置..."
SCRIPT_DIR="$HOME/servo_project"
mkdir -p "$SCRIPT_DIR"

# servo_control.py をコピー（同じディレクトリにあることを想定）
if [ -f "$(dirname "$0")/servo_control.py" ]; then
    cp "$(dirname "$0")/servo_control.py" "$SCRIPT_DIR/"
    echo "  ✓ servo_control.py をコピーしました → $SCRIPT_DIR/"
fi
if [ -f "$(dirname "$0")/ina226_logger.py" ]; then
    cp "$(dirname "$0")/ina226_logger.py" "$SCRIPT_DIR/"
    echo "  ✓ ina226_logger.py をコピーしました → $SCRIPT_DIR/"
fi
if [ -f "$(dirname "$0")/servo_with_logging.py" ]; then
    cp "$(dirname "$0")/servo_with_logging.py" "$SCRIPT_DIR/"
    echo "  ✓ servo_with_logging.py をコピーしました → $SCRIPT_DIR/"
fi

echo ""
echo "========================================"
echo " セットアップ完了！"
echo "========================================"
echo ""
echo "【仮想環境の使い方】"
echo "  source ~/servo_env/bin/activate    # 仮想環境を有効化"
echo "  python servo_control.py            # サーボ制御テスト"
echo "  python ina226_logger.py            # INA226 電圧ロギング"
echo "  python servo_with_logging.py       # 両方同時実行"
echo "  deactivate                         # 仮想環境を終了"
echo ""
echo "【I2C アドレス確認】"
echo "  i2cdetect -y 1"
echo "    PCA9685 → 0x70 (i2cdetect表示: 70)"
echo "    INA226  → 0x40 (i2cdetect表示: 40)"
echo ""