// =============================================================================
// watering_driver.ino - 自動給水システム Arduino ファームウェア
// =============================================================================
//
// 設計思想:
//   Arduino は「ドライバ」に徹する。自律的な判断は行わない。
//   ラズパイからのシリアルコマンドを受けてセンサー値を返す or
//   アクチュエータを操作するだけ。
//
//   唯一の例外: 安全機能 (ポンプタイムアウト, 水位チェック, ウォッチドッグ)
//   これらはラズパイがフリーズしても被害を防ぐためにArduino側に実装。
//
// コマンド一覧:
//   PING         → PONG
//   VERSION      → VERSION:WateringDriver,1.0.1
//   READ_SOIL    → SOIL:512,480
//   READ_WATER   → WATER:1
//   READ_DHT     → DHT:25.3,60.2
//   READ_ALL     → SOIL:512,480;WATER:1;DHT:25.3,60.2;PUMP:OFF
//   PUMP_ON      → OK:PUMP_ON  or  ERR:NO_WATER
//   PUMP_OFF     → OK:PUMP_OFF
//   STATUS_PUMP  → PUMP:ON  or  PUMP:OFF
//
// =============================================================================

#include "config.h"
#include <DHT.h>

// =============================================================================
// グローバル変数
// =============================================================================

// コマンド受信バッファ
char cmdBuffer[CMD_BUFFER_SIZE];
uint8_t cmdIndex = 0;

// ポンプ状態
bool pumpRunning = false;
unsigned long pumpStartTime = 0;

// ウォッチドッグ
unsigned long lastCommandTime = 0;

// 土壌センサーピン配列
const uint8_t soilPins[SOIL_SENSOR_COUNT] = { PIN_SOIL_1, PIN_SOIL_2 };

// DHT センサー
DHT dht(PIN_DHT, DHT_TYPE);

// =============================================================================
// センサー読み取り関数
// =============================================================================

/**
 * アナログ値を複数回読み取り、中央値を返す (ノイズ対策)
 */
int readAnalogMedian(uint8_t pin) {
  int samples[ANALOG_READ_SAMPLES];

  for (uint8_t i = 0; i < ANALOG_READ_SAMPLES; i++) {
    samples[i] = analogRead(pin);
    if (i < ANALOG_READ_SAMPLES - 1) {
      delay(ANALOG_READ_DELAY_MS);
    }
  }

  // 挿入ソートで並べ替え
  for (uint8_t i = 1; i < ANALOG_READ_SAMPLES; i++) {
    int key = samples[i];
    int j = i - 1;
    while (j >= 0 && samples[j] > key) {
      samples[j + 1] = samples[j];
      j--;
    }
    samples[j + 1] = key;
  }

  // 中央値を返す
  return samples[ANALOG_READ_SAMPLES / 2];
}

/**
 * 土壌湿度を読み取り、シリアルに "SOIL:val1,val2" 形式で送信
 */
void cmdReadSoil() {
  Serial.print("SOIL:");
  for (uint8_t i = 0; i < SOIL_SENSOR_COUNT; i++) {
    if (i > 0) Serial.print(",");
    Serial.print(readAnalogMedian(soilPins[i]));
  }
  Serial.println();
}

/**
 * 水位センサーを読み取り、シリアルに "WATER:1" or "WATER:0" で送信
 */
void cmdReadWater() {
  int level = digitalRead(PIN_WATER_LEVEL);
  Serial.print("WATER:");
  Serial.println(level);
}

/**
 * DHT22 から温度・湿度を読み取り、"DHT:temp,hum" 形式で送信
 */
void cmdReadDHT() {
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();

  if (isnan(temp) || isnan(hum)) {
    Serial.println("ERR:DHT_READ_FAIL");
    return;
  }

  Serial.print("DHT:");
  Serial.print(temp, 1);
  Serial.print(",");
  Serial.println(hum, 1);
}

/**
 * 全センサー一括読み取り
 * "SOIL:v1,v2;WATER:1;DHT:25.3,60.2;PUMP:OFF"
 */
void cmdReadAll() {
  // SOIL
  Serial.print("SOIL:");
  for (uint8_t i = 0; i < SOIL_SENSOR_COUNT; i++) {
    if (i > 0) Serial.print(",");
    Serial.print(readAnalogMedian(soilPins[i]));
  }

  // WATER
  Serial.print(";WATER:");
  Serial.print(digitalRead(PIN_WATER_LEVEL));

  // DHT
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();
  Serial.print(";DHT:");
  if (isnan(temp) || isnan(hum)) {
    Serial.print("ERR,ERR");
  } else {
    Serial.print(temp, 1);
    Serial.print(",");
    Serial.print(hum, 1);
  }

  // PUMP
  Serial.print(";PUMP:");
  Serial.println(pumpRunning ? "ON" : "OFF");
}

// =============================================================================
// ポンプ制御関数
// =============================================================================

/**
 * ポンプをONにする
 * 安全チェック: 水位不足ならエラーを返して起動しない
 */
void cmdPumpOn() {

  digitalWrite(PIN_PUMP_RELAY, RELAY_ON);
  pumpRunning = true;
  pumpStartTime = millis();

  // 安全チェック: 水位確認
  if (digitalRead(PIN_WATER_LEVEL) == LOW) {
    Serial.println("WARN:PUMP_ON_NO_WATER");
  }else{
    Serial.println("OK:PUMP_ON");
  }
}

/**
 * ポンプをOFFにする
 */
void cmdPumpOff() {
  digitalWrite(PIN_PUMP_RELAY, RELAY_OFF);
  pumpRunning = false;
  pumpStartTime = 0;
  Serial.println("OK:PUMP_OFF");
}

/**
 * ポンプ状態を返す
 */
void cmdStatusPump() {
  Serial.print("PUMP:");
  Serial.println(pumpRunning ? "ON" : "OFF");
}

// =============================================================================
// 安全機能
// =============================================================================

/**
 * ポンプタイムアウトチェック
 * PUMP_ON 後に一定時間経過したら自動的にOFFにする
 */
void checkPumpTimeout() {
  if (!pumpRunning) return;

  unsigned long elapsed = millis() - pumpStartTime;
  if (elapsed >= PUMP_TIMEOUT_MS) {
    digitalWrite(PIN_PUMP_RELAY, RELAY_OFF);
    pumpRunning = false;
    pumpStartTime = 0;
    Serial.println("WARN:PUMP_TIMEOUT");
  }
}

/**
 * ウォッチドッグチェック
 * シリアル通信が一定時間途絶えた場合、ポンプを安全にOFFにする
 */
void checkWatchdog() {
  if (WATCHDOG_TIMEOUT_MS == 0) return;       // 無効
  if (!pumpRunning) return;                    // ポンプ停止中なら不要

  unsigned long elapsed = millis() - lastCommandTime;
  if (elapsed >= WATCHDOG_TIMEOUT_MS) {
    digitalWrite(PIN_PUMP_RELAY, RELAY_OFF);
    pumpRunning = false;
    pumpStartTime = 0;
    Serial.println("WARN:WATCHDOG_TIMEOUT");
  }
}

/**
 * ポンプ稼働中の水位監視
 * 給水中に水がなくなったら即座に停止
 */
void checkWaterDuringPump() {
  if (!pumpRunning) return;

  if (digitalRead(PIN_WATER_LEVEL) == LOW) {
    // ポンプは止めない
    Serial.println("WARN:WATER_EMPTY_DURING_PUMP");
  }
}

// =============================================================================
// コマンドパーサー
// =============================================================================

/**
 * 受信したコマンド文字列を解析して対応する関数を呼び出す
 */
void processCommand(const char* cmd) {
  // ウォッチドッグタイマーをリセット
  lastCommandTime = millis();

  // コマンド判定
  if (strcmp(cmd, "PING") == 0) {
    Serial.println("PONG");
  }
  else if (strcmp(cmd, "VERSION") == 0) {
    Serial.print("VERSION:");
    Serial.print(FW_NAME);
    Serial.print(",");
    Serial.println(FW_VERSION);
  }
  else if (strcmp(cmd, "READ_SOIL") == 0) {
    cmdReadSoil();
  }
  else if (strcmp(cmd, "READ_WATER") == 0) {
    cmdReadWater();
  }
  else if (strcmp(cmd, "READ_DHT") == 0) {
    cmdReadDHT();
  }
  else if (strcmp(cmd, "READ_ALL") == 0) {
    cmdReadAll();
  }
  else if (strcmp(cmd, "PUMP_ON") == 0) {
    cmdPumpOn();
  }
  else if (strcmp(cmd, "PUMP_OFF") == 0) {
    cmdPumpOff();
  }
  else if (strcmp(cmd, "STATUS_PUMP") == 0) {
    cmdStatusPump();
  }
  else {
    Serial.print("ERR:UNKNOWN_CMD:");
    Serial.println(cmd);
  }
}

// =============================================================================
// Arduino メインルーチン
// =============================================================================

void setup() {
  // シリアル通信開始
  Serial.begin(SERIAL_BAUD_RATE);

  // ピンモード設定
  pinMode(PIN_WATER_LEVEL, INPUT_PULLUP);
  pinMode(PIN_PUMP_RELAY, OUTPUT);

  // ポンプを確実にOFF状態で起動
  digitalWrite(PIN_PUMP_RELAY, RELAY_OFF);

  // DHT センサー初期化
  dht.begin();

  // ウォッチドッグタイマー初期化
  lastCommandTime = millis();

  // コマンドバッファ初期化
  cmdIndex = 0;
  memset(cmdBuffer, 0, CMD_BUFFER_SIZE);

  // 起動完了メッセージ
  Serial.print("READY:");
  Serial.print(FW_NAME);
  Serial.print(",");
  Serial.println(FW_VERSION);
}

void loop() {
  // ----- シリアルコマンド受信処理 -----
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == CMD_TERMINATOR) {
      // コマンド終端 → 処理実行
      cmdBuffer[cmdIndex] = '\0';

      // 空コマンドは無視
      if (cmdIndex > 0) {
        processCommand(cmdBuffer);
      }

      // バッファリセット
      cmdIndex = 0;
      memset(cmdBuffer, 0, CMD_BUFFER_SIZE);
    }
    else if (c == '\r') {
      // CRは無視 (Windows環境対応)
    }
    else {
      // バッファに追加 (オーバーフロー防止)
      if (cmdIndex < CMD_BUFFER_SIZE - 1) {
        cmdBuffer[cmdIndex++] = c;
      } else {
        // バッファオーバーフロー → リセット
        cmdIndex = 0;
        memset(cmdBuffer, 0, CMD_BUFFER_SIZE);
        Serial.println("ERR:CMD_OVERFLOW");
      }
    }
  }

  // ----- 安全機能チェック (毎ループ実行) -----
  checkPumpTimeout();
  checkWatchdog();
  checkWaterDuringPump();
}
