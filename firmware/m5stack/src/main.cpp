/*
  main.cpp - M5Stack Servo Logger
  ================================
  M5Stack Basic + PCA9685 によるサーボ3ch制御 + PWM計測
  Raspberry Pi へシリアルでデータ送信

  【配線】
  M5Stack G21 (SDA) → PCA9685 SDA
  M5Stack G22 (SCL) → PCA9685 SCL
  M5Stack 3.3V      → PCA9685 VCC
  M5Stack GND       → PCA9685 GND
  外部電源 5〜6V    → PCA9685 V+
  GND 共通

  PWM計測ピン:
  PCA9685 ch0信号 → M5Stack G36
  PCA9685 ch1信号 → M5Stack G26
  PCA9685 ch2信号 → M5Stack G17

  【シリアル通信】
  USB → Raspberry Pi (115200bps)

  【送信フォーマット】
  timestamp_ms,pulse_ch0,pulse_ch1,pulse_ch2

  【受信コマンド】
  s          → 計測開始
  p          → 計測停止
  r          → リセット
  a<ch><deg> → 角度指定 (例: a0090 = ch0を90度)
  e<ch><1/0> → サーボON/OFF (例: e01 = ch0をON)
  E<1/0>     → 全サーボON/OFF
  w<1/0>     → スイープON/OFF
*/

#include <M5Stack.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ─── ピン設定 ──────────────────────────────────────────────
#define PIN_CH0  26
#define PIN_CH1  35
#define PIN_CH2  36

// ─── PCA9685 設定 ──────────────────────────────────────────
#define PCA_ADDR  0x41
#define PWM_FREQ  50
#define SERVO_MIN 102   // 500μs  = 0度
#define SERVO_MAX 512   // 2500μs = 180度

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA_ADDR);

// ─── 状態 ──────────────────────────────────────────────────
bool     isRunning       = false;
uint32_t startTime       = 0;
bool     servoEnabled[3] = {false, false, false};
float    servoAngle[3]   = {90, 90, 90};
bool     sweepActive     = false;
float    sweepAngle      = 0;
int      sweepDir        = 1;
uint32_t lastSweep       = 0;

const unsigned long PULSE_TIMEOUT  = 25000;
const int           SWEEP_STEP_MS  = 20;
const float         SWEEP_STEP_DEG = 1.8;

// ─── サーボ制御 ───────────────────────────────────────────
void setAngle(uint8_t ch, float angle) {
  angle = constrain(angle, 0, 180);
  servoAngle[ch] = angle;
  if (!servoEnabled[ch]) return;
  uint16_t pulse = SERVO_MIN + (uint16_t)((SERVO_MAX - SERVO_MIN) * angle / 180.0);
  pca.setPWM(ch, 0, pulse);
}

void stopServo(uint8_t ch) {
  pca.setPWM(ch, 0, 0);
}

// ─── 画面表示 ──────────────────────────────────────────────
void updateDisplay() {
  M5.Lcd.fillScreen(BLACK);

  M5.Lcd.setTextColor(CYAN);
  M5.Lcd.setTextSize(2);
  M5.Lcd.setCursor(4, 4);
  M5.Lcd.print("SERVO LOGGER");

  M5.Lcd.setTextColor(isRunning ? GREEN : RED);
  M5.Lcd.setTextSize(1);
  M5.Lcd.setCursor(220, 8);
  M5.Lcd.print(isRunning ? "REC" : "---");

  const uint16_t colors[] = {CYAN, 0xFB40, 0xAC5F};
  const char* names[]     = {"CH0", "CH1", "CH2"};

  for (int ch = 0; ch < 3; ch++) {
    int y = 40 + ch * 60;
    M5.Lcd.setTextColor(colors[ch]);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setCursor(4, y);
    M5.Lcd.print(names[ch]);

    M5.Lcd.setTextColor(servoEnabled[ch] ? GREEN : DARKGREY);
    M5.Lcd.setCursor(60, y);
    M5.Lcd.print(servoEnabled[ch] ? "ON " : "OFF");

    M5.Lcd.setTextColor(WHITE);
    M5.Lcd.setCursor(110, y);
    M5.Lcd.printf("%.0f deg", servoAngle[ch]);
  }

  M5.Lcd.setTextColor(DARKGREY);
  M5.Lcd.setTextSize(1);
  M5.Lcd.setCursor(4,   220); M5.Lcd.print("A:ALL ON");
  M5.Lcd.setCursor(120, 220); M5.Lcd.print("B:ALL OFF");
  M5.Lcd.setCursor(230, 220); M5.Lcd.print("C:SWEEP");
}

// ─── スイープ更新 ─────────────────────────────────────────
void updateSweep() {
  if (!sweepActive) return;
  uint32_t now = millis();
  if (now - lastSweep < SWEEP_STEP_MS) return;
  lastSweep = now;

  sweepAngle += sweepDir * SWEEP_STEP_DEG;
  if (sweepAngle >= 180) { sweepAngle = 180; sweepDir = -1; }
  if (sweepAngle <= 0)   { sweepAngle = 0;   sweepDir =  1; }

  for (int ch = 0; ch < 3; ch++) setAngle(ch, sweepAngle);
}

// ─── シリアルコマンド処理 ──────────────────────────────────
void processCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  char c = cmd.charAt(0);

  if (c == 's') {
    startTime = millis();
    isRunning = true;
    Serial.println("# START");

  } else if (c == 'p') {
    isRunning = false;
    Serial.println("# STOP");

  } else if (c == 'r') {
    isRunning = false;
    Serial.println("# RESET");

  } else if (c == 'a' && cmd.length() >= 5) {
    int   ch  = cmd.charAt(1) - '0';
    float ang = cmd.substring(2).toFloat();
    if (ch >= 0 && ch <= 2) {
      servoEnabled[ch] = true;
      setAngle(ch, ang);
      Serial.printf("# ANGLE ch%d=%.0f\n", ch, ang);
    }

  } else if (c == 'e' && cmd.length() >= 3) {
    int ch  = cmd.charAt(1) - '0';
    int ena = cmd.charAt(2) - '0';
    if (ch >= 0 && ch <= 2) {
      servoEnabled[ch] = (ena == 1);
      if (!servoEnabled[ch]) stopServo(ch);
      else setAngle(ch, servoAngle[ch]);
      Serial.printf("# SERVO ch%d=%s\n", ch, servoEnabled[ch] ? "ON" : "OFF");
    }

  } else if (c == 'E' && cmd.length() >= 2) {
    int ena = cmd.charAt(1) - '0';
    for (int ch = 0; ch < 3; ch++) {
      servoEnabled[ch] = (ena == 1);
      if (!servoEnabled[ch]) stopServo(ch);
      else setAngle(ch, servoAngle[ch]);
    }
    Serial.printf("# ALL SERVO %s\n", ena ? "ON" : "OFF");

  } else if (c == 'w' && cmd.length() >= 2) {
    sweepActive = (cmd.charAt(1) == '1');
    if (sweepActive) { sweepAngle = 0; sweepDir = 1; }
    Serial.printf("# SWEEP %s\n", sweepActive ? "ON" : "OFF");
  }

  updateDisplay();
}

// ─── セットアップ ─────────────────────────────────────────
void setup() {
  M5.begin();
  Serial.begin(115200);

  Wire.begin(21, 22);
  pca.begin();
  pca.setPWMFreq(PWM_FREQ);

  pinMode(PIN_CH0, INPUT);
  pinMode(PIN_CH1, INPUT);
  pinMode(PIN_CH2, INPUT);

  Serial.println("# M5Stack Servo Logger Ready");
  Serial.println("# Format: timestamp_ms,pulse_ch0,pulse_ch1,pulse_ch2");
  Serial.println("# Commands: s=start p=stop r=reset");

  updateDisplay();
}

// ─── メインループ ─────────────────────────────────────────
void loop() {
  M5.update();

  if (M5.BtnA.wasPressed()) {
    for (int ch = 0; ch < 3; ch++) {
      servoEnabled[ch] = true;
      setAngle(ch, servoAngle[ch]);
    }
    Serial.println("# ALL SERVO ON");
    updateDisplay();
  }

  if (M5.BtnB.wasPressed()) {
    for (int ch = 0; ch < 3; ch++) {
      servoEnabled[ch] = false;
      stopServo(ch);
    }
    sweepActive = false;
    Serial.println("# ALL SERVO OFF");
    updateDisplay();
  }

  if (M5.BtnC.wasPressed()) {
    sweepActive = !sweepActive;
    if (sweepActive) {
      sweepAngle = 0; sweepDir = 1;
      for (int ch = 0; ch < 3; ch++) servoEnabled[ch] = true;
    }
    Serial.printf("# SWEEP %s\n", sweepActive ? "ON" : "OFF");
    updateDisplay();
  }

  updateSweep();

  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    processCommand(cmd);
  }

  if (isRunning) {
    unsigned long p0 = pulseIn(PIN_CH0, HIGH, PULSE_TIMEOUT);
    unsigned long p1 = pulseIn(PIN_CH1, HIGH, PULSE_TIMEOUT);
    unsigned long p2 = pulseIn(PIN_CH2, HIGH, PULSE_TIMEOUT);

    if (p0 > 0 || p1 > 0 || p2 > 0) {
      uint32_t ts = millis() - startTime;
      Serial.printf("%lu,%lu,%lu,%lu\n", ts, p0, p1, p2);
    }
  }
}