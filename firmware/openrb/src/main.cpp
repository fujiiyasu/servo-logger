/*
  openrb_pulsein.ino
  ==================
  OpenRB-150 3チャンネルPWMパルス幅計測
  - D4: サーボch2対応
  - D5: サーボch1対応
  - D6: サーボch0対応

  【送信フォーマット】
    timestamp_ms,pulse_d4,pulse_d5,pulse_d6
    例: 1000,1500,1200,1800

  【コマンド】
    's' → 計測開始
    'p' → 計測停止
    'r' → リセット
*/

const int  PIN_CH2   = 4;   // サーボch2対応
const int  PIN_CH1   = 5;   // サーボch1対応
const int  PIN_CH0   = 6;   // サーボch0対応
const int  BAUD_RATE = 115200;
const unsigned long TIMEOUT_US = 25000;  // 25ms タイムアウト

bool     isRunning = false;
uint32_t startTime = 0;

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial && millis() < 3000);

  pinMode(PIN_CH0, INPUT);
  pinMode(PIN_CH1, INPUT);
  pinMode(PIN_CH2, INPUT);

  Serial.println("# OpenRB-150 3ch PulseIn Logger Ready");
  Serial.println("# Pins: D6=ch0, D5=ch1, D4=ch2");
  Serial.println("# Format: timestamp_ms,pulse_ch0,pulse_ch1,pulse_ch2");
  Serial.println("# Commands: s=start p=stop r=reset");
}

void loop() {
  // コマンド受信
  while (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    if (cmd == 's') {
      startTime = millis();
      isRunning = true;
      Serial.println("# START");
    } else if (cmd == 'p') {
      isRunning = false;
      Serial.println("# STOP");
    } else if (cmd == 'r') {
      isRunning = false;
      Serial.println("# RESET");
    }
  }

  if (!isRunning) return;

  // 3チャンネル順番に計測
  // pulseIn はブロッキングだが各チャンネル最大25msなので合計75ms以内
  unsigned long p0 = pulseIn(PIN_CH0, HIGH, TIMEOUT_US);
  unsigned long p1 = pulseIn(PIN_CH1, HIGH, TIMEOUT_US);
  unsigned long p2 = pulseIn(PIN_CH2, HIGH, TIMEOUT_US);

  // いずれか1つでも有効なら送信
  if (p0 == 0 && p1 == 0 && p2 == 0) return;

  uint32_t ts = millis() - startTime;
  Serial.print(ts);
  Serial.print(',');
  Serial.print(p0);
  Serial.print(',');
  Serial.print(p1);
  Serial.print(',');
  Serial.println(p2);
}
