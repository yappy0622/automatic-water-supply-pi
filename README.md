# Auto Watering System

Raspberry Pi + Arduino による自動給水システム

## システム概要

```
スマートフォン (Google Spreadsheet)
        │
        ▼
  Raspberry Pi  ── USB Serial ──  Arduino
  (制御・ロジック)                  (センサー・ポンプ)
```

- **Arduino**: センサー読み取り・ポンプ制御のみ（ドライバ層）
- **Raspberry Pi**: 判定ロジック・スケジューリング・外部連携（頭脳）
- **Google Spreadsheet**: スマホからの設定変更・データ記録

## ディレクトリ構成

```
.
├── README.md
├── docs/
│   └── system_design.md          # システム設計書（全体像）
├── arduino/
│   └── watering_driver/
│       ├── watering_driver.ino   # Arduino ファームウェア
│       └── config.h              # ピン定義・定数設定
└── raspi/
    ├── arduino/
    │   ├── __init__.py
    │   └── serial_driver.py      # シリアル通信ドライバ (Python)
    └── tests/
        ├── __init__.py
        ├── mock_arduino.py       # Arduino シミュレータ (実機不要テスト)
        └── test_serial.py        # シリアルドライバ テスト
```

## 言語選定

### Arduino: C++ (Arduino C++)

| 候補 | 判定 | 理由 |
|------|------|------|
| **C++ (Arduino)** | **採用** | エコシステムが完璧。DHT22等のライブラリがそのまま使える。情報量が圧倒的。一度書いたら変更しない設計と相性が良い |
| Rust (AVR) | 不採用 | 2025年にAVR公式サポートが入ったが、まだ実験的。DHTライブラリ等の互換性が不十分。学習コストに対してリターンが少ない（ファームウェアは小さく変更しない前提） |
| Go (TinyGo) | 不採用 | AVRバックエンドが実験的。8bit Arduino でのパフォーマンスに課題。シリアル通信サポートが限定的 |

> **設計上の判断**: Arduino は「一度書き込んだら基本的に変更しない最小ドライバ」。
> Rust/Goの安全性メリットは、変更頻度の高いRaspberry Pi側（Python）で活かす方が効果的。
> 将来ラズパイ側をGoやRustに置き換えることは十分ありうる。

### Raspberry Pi: Python
- pyserialでシリアル通信
- 後続Phase でGoogleSpreadsheet API、Discord連携等を追加しやすい

## Arduino ファームウェア

### コマンド一覧

| コマンド | レスポンス | 説明 |
|----------|-----------|------|
| `PING` | `PONG` | ヘルスチェック |
| `VERSION` | `VERSION:WateringDriver,1.0.0` | FWバージョン |
| `READ_SOIL` | `SOIL:512,480` | 土壌湿度 (各センサーの生値) |
| `READ_WATER` | `WATER:1` | 水位 (1=正常, 0=不足) |
| `READ_DHT` | `DHT:25.3,60.2` | 温度,湿度 |
| `READ_ALL` | `SOIL:512,480;WATER:1;DHT:25.3,60.2;PUMP:OFF` | 一括取得 |
| `PUMP_ON` | `OK:PUMP_ON` or `ERR:NO_WATER` | ポンプ起動 |
| `PUMP_OFF` | `OK:PUMP_OFF` | ポンプ停止 |
| `STATUS_PUMP` | `PUMP:ON` or `PUMP:OFF` | ポンプ状態確認 |

### 安全機能 (Arduino側にハードコード)

| 機能 | 内容 |
|------|------|
| ポンプ自動OFF | PUMP_ON後 60秒で自動停止 (`WARN:PUMP_TIMEOUT`) |
| 水位不足ガード | 水位0のとき PUMP_ON を拒否 (`ERR:NO_WATER`) |
| 給水中水位監視 | 給水中に水がなくなったら即停止 (`WARN:WATER_EMPTY_DURING_PUMP`) |
| ウォッチドッグ | 通信途絶 5分でポンプ停止 (`WARN:WATCHDOG_TIMEOUT`) |

### Arduino への書き込み

1. Arduino IDE を開く
2. `arduino/watering_driver/watering_driver.ino` を開く
3. ライブラリマネージャから **DHT sensor library** (Adafruit) をインストール
4. ボードとポートを選択して書き込み

`config.h` でピン番号やタイムアウト値を変更可能。

## 開発・テスト (実機なし)

Arduino 実機がなくても、モックシミュレータでドライバの動作確認ができます。

```bash
# 依存インストール
pip install pyserial

# ターミナル1: モック Arduino 起動
cd raspi/tests
python mock_arduino.py

# ターミナル2: テスト実行
cd raspi/tests
python test_serial.py --port /tmp/mock_arduino
```

モック Arduino のターミナルで状態を変更できます:
- `dry` - 土壌を乾燥状態にする
- `wet` - 土壌を湿潤状態にする
- `water_empty` - 水位を不足にする
- `water_full` - 水位を正常にする

## 実装ロードマップ

- [x] **Phase 1-a**: Arduino ファームウェア
- [x] **Phase 1-a**: ラズパイ シリアルドライバ + テストツール
- [ ] **Phase 1-b**: 給水判定ロジック + スケジューラ
- [ ] **Phase 2**: Google Spreadsheet 連携 + 通知
- [ ] **Phase 3**: データ可視化 + カメラ
- [ ] **Phase 4**: Webダッシュボード + 発展機能

詳細な設計は [docs/system_design.md](docs/system_design.md) を参照。
