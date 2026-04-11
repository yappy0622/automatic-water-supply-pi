# Auto Watering System

Raspberry Pi + Arduino による自動給水システム

## システム概要

```
┌──────────────┐
│  スマートフォン  │
│  (ブラウザ)    │
└──────┬───────┘
       │ Google Spreadsheet で設定変更 / データ閲覧
       ▼
┌──────────────────────────────────────────────────┐
│              Google Spreadsheet                   │
│  「設定」シート ← スマホから書き込み                     │
│  「センサーログ」「給水履歴」← ラズパイが書き込み           │
└──────────────────────┬───────────────────────────┘
                       │ Google Sheets API (30分ポーリング)
                       ▼
┌──────────────────────────────────────────────────┐
│  Raspberry Pi 5 (8GB)                             │
│                                                   │
│  main.py ─┬─ スケジューラ (定時給水判定)              │
│           ├─ ConfigManager (yaml + Sheets マージ)  │
│           ├─ WateringController (給水判定・実行)      │
│           ├─ SheetsClient (設定読取/ログ書込)         │
│           ├─ ArduinoDriver (シリアル通信)            │
│           ├─ SensorCSVLogger (ローカルCSV記録)       │
│           ├─ SensorGrapher (グラフ生成)              │
│           └─ DiscordNotifier (Discord通知)          │
└──────────────────────┬───────────────────────────┘
                       │ USB Serial
                       ▼
┌──────────────────────────────────────────────────┐
│  Arduino Nano 互換 (USB Type-C)                   │
│  watering_driver.ino (コマンド応答のみ)              │
│  ├─ 土壌湿度センサー ×2 (静電容量式)                  │
│  ├─ 水位センサー ×1 (フロートスイッチ)                 │
│  ├─ 温湿度センサー (DHT22)                          │
│  ├─ 照度センサー (LDR + 10kΩ分圧)                   │
│  ├─ EC/TDSセンサー (土壌肥料濃度モニタリング)         │
│  └─ ラッチリレー → 給水ポンプ                         │
└──────────────────────────────────────────────────┘
```

## 使用ハードウェア

| 部品 | 型番・仕様 |
|------|-----------|
| マイコン (制御) | **Raspberry Pi 5 (8GB RAM)** |
| マイコン (I/O) | **Arduino Nano 互換 (USB Type-C)** |
| 土壌湿度センサー | 静電容量式 ×2 (例: DIYStudio A1305269P) |
| 水位センサー | フロートスイッチ ×1 |
| 温湿度センサー | DHT22 |
| 照度センサー | LDR (フォトレジスタ) + 10kΩ抵抗 (分圧回路) |
| ポンプ制御 | ラッチリレー |
| 給水ポンプ | USB給水ポンプ |
| 接続 | Raspberry Pi ⇔ Arduino: USB (Type-C) |

### 追加センサー候補 (購入検討用)

| センサー | 概算費用 | 用途 | おすすめ度 |
|---------|---------|------|-----------|
| BH1750 デジタル照度センサー | ¥300-500 | LDR より高精度な照度計測 (I2C接続) | ★★★★ |
| CCS811 / SGP30 CO₂センサー | ¥1,500-2,500 | 室内CO₂濃度 (植物の光合成効率と相関) | ★★★ |
| 雨滴センサー | ¥200-400 | 屋外設置時の降雨検知 → 給水スキップ | ★★★ (屋外のみ) |
| EC (電気伝導度) センサー | ¥2,000-4,000 | 土壌の肥料濃度モニタリング | ★★ (上級者向け) |
| 防水温度センサー (DS18B20) | ¥300-500 | 土壌温度の計測 (根の健康度) | ★★ |
| UV センサー (VEML6075) | ¥500-800 | 紫外線量 (日焼け・植物ストレス) | ★★ |

## ディレクトリ構成

```
.
├── README.md
├── docs/
│   └── system_design.md              # システム設計書
├── arduino/
│   └── watering_driver/
│       ├── watering_driver.ino       # Arduino ファームウェア (v1.1.0)
│       └── config.h                  # ピン定義・定数設定
└── raspi/
    ├── main.py                       # エントリポイント (メインループ)
    ├── config.yaml                   # ローカル設定 (デフォルト値)
    ├── config_manager.py             # 設定管理 (yaml + Sheets マージ)
    ├── requirements.txt              # Python 依存パッケージ
    ├── arduino/
    │   ├── __init__.py
    │   └── serial_driver.py          # シリアル通信ドライバ
    ├── logic/
    │   ├── __init__.py
    │   └── watering.py               # 給水判定・実行ロジック
    ├── external/
    │   ├── __init__.py
    │   ├── sheets.py                 # Google Spreadsheet 連携
    │   └── discord_notify.py         # Discord 通知
    ├── data/
    │   ├── __init__.py
    │   ├── logger.py                 # ログ設定 (ローテーション付き)
    │   ├── sensor_log.py             # ローカル CSV センサーログ
    │   └── grapher.py                # グラフ生成 (matplotlib)
    └── tests/
        ├── __init__.py
        ├── mock_arduino.py           # Arduino シミュレータ
        └── test_serial.py            # シリアルドライバ テスト
```

## セットアップ

### 1. Arduino ファームウェアの書き込み

1. Arduino IDE を開く
2. `arduino/watering_driver/watering_driver.ino` を開く
3. ライブラリマネージャから **DHT sensor library** (Adafruit) をインストール
4. ボード: **Arduino Nano** を選択
5. `config.h` でピン番号を確認・調整してから書き込み

**ピン配置 (config.h):**

| ピン | 用途 |
|------|------|
| A0 | 土壌湿度センサー 1 |
| A1 | 土壌湿度センサー 2 |
| A2 | 照度センサー (LDR) |
| D2 | 水位センサー (フロートスイッチ) |
| D4 | DHT22 温湿度センサー |
| D7 | ポンプ制御リレー |

### 2. Raspberry Pi のセットアップ

```bash
# リポジトリをクローン
git clone https://github.com/yappy0622/automatic-water-supply-pi.git
cd automatic-water-supply-pi/raspi

# 依存インストール
pip install -r requirements.txt

# 設定ファイルを編集
cp config.yaml config.yaml.bak
nano config.yaml
# → arduino.port を実際のポートに変更 (例: /dev/ttyUSB0, /dev/ttyACM0)
```

### 3. Google Spreadsheet 連携 (任意)

Spreadsheet 連携を使うと、スマホから設定変更・データ閲覧ができます。

#### 3-1. Google Cloud 側の準備

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. **Google Sheets API** を有効化
3. **サービスアカウント** を作成し、JSON キーをダウンロード
4. キーファイルを `raspi/credentials.json` に配置

#### 3-2. Spreadsheet の準備

1. 新しいスプレッドシートを作成
2. 3つのシートを作成:

**「設定」シート** (スマホから値を変更する):

| A列 (項目) | B列 (値) | 説明 |
|------------|---------|------|
| 土壌湿度閾値 | `400` | この値以下で給水 |
| 給水時間(秒) | `10` | ポンプ稼働時間 |
| スケジュール時刻 | `07:00` | カンマ区切りで複数可 |
| 給水モード | `AUTO` | AUTO / MANUAL / OFF |
| 手動給水 | `FALSE` | TRUE にすると即時給水 |
| 通知 | `TRUE` | 通知の有効/無効 |

**「センサーログ」シート**: ヘッダ行のみ作成

```
タイムスタンプ | 土壌1 | 土壌2 | 水位 | 温度 | 湿度 | 照度 | ポンプ | 備考
```

**「給水履歴」シート**: ヘッダ行のみ作成

```
タイムスタンプ | トリガー | 給水前湿度 | 給水時間(秒) | 給水後湿度 | 結果
```

3. スプレッドシートをサービスアカウントのメールアドレスに **編集者** として共有
4. `config.yaml` を編集:

```yaml
google_sheets:
  enabled: true
  credentials_file: "credentials.json"
  spreadsheet_id: "ここにスプレッドシートIDを貼る"
```

### 4. Discord 通知 (任意)

1. Discord サーバーの設定 → 連携サービス → ウェブフック → 新しいウェブフック
2. ウェブフック URL をコピー
3. `config.yaml` に設定:

```yaml
notification:
  discord_webhook_url: "https://discord.com/api/webhooks/..."
  notify_on_watering: true
  notify_on_low_water: true
  notify_on_error: true
```

通知内容:
- 給水実行レポート (成功/失敗、土壌湿度の変化)
- 水不足アラート
- エラー通知
- センサーデータグラフ (6時間ごとに自動送信)

### 5. 起動

```bash
cd raspi

# テスト: 1回だけ給水判定して終了
python main.py --once

# 通常起動 (常駐)
python main.py

# バックグラウンドで起動
nohup python main.py > /dev/null 2>&1 &
```

## 設定の仕組み

```
優先度: Google Spreadsheet の値 > config.yaml の値
```

- `config.yaml` がデフォルト値として常に読み込まれる
- `google_sheets.enabled: true` の場合、Spreadsheet の値でデフォルトが **上書き** される
- Spreadsheet が接続不能な場合は `config.yaml` の値にフォールバック
- Spreadsheet のポーリング間隔は `schedule.sheets_poll_interval_min` で設定 (デフォルト: 30分)

### スマホからの操作例

| やりたいこと | 操作 |
|-------------|------|
| 閾値を変えたい | 「設定」シート B2 の値を変更 → 次回ポーリングで反映 |
| 今すぐ水やりしたい | 「設定」シート B6 を `TRUE` に → ラズパイが検知して即時給水 |
| 水やりを止めたい | 「設定」シート B5 を `OFF` に |
| センサーデータを見たい | 「センサーログ」シートを開く |

## 省電力設計

| パラメータ | デフォルト値 | 説明 |
|-----------|------------|------|
| `main_loop_sleep_sec` | 30秒 | メインループのスリープ間隔 |
| `sensor_interval_min` | 30分 | センサー定期取得の間隔 |
| `sheets_poll_interval_min` | 30分 | Spreadsheet ポーリング間隔 |
| `graph_interval_hours` | 6時間 | グラフ自動生成間隔 |

センサー記録と Spreadsheet ポーリングを同じ 30 分周期に統合し、API 呼び出しと CPU 使用を最小限にしています。

## Arduino ファームウェア (v1.1.0)

### コマンド一覧

| コマンド | レスポンス | 説明 |
|----------|-----------|------|
| `PING` | `PONG` | ヘルスチェック |
| `VERSION` | `VERSION:WateringDriver,1.1.0` | FWバージョン |
| `READ_SOIL` | `SOIL:512,480` | 土壌湿度 (各センサーの生値) |
| `READ_WATER` | `WATER:1` | 水位 (1=正常, 0=不足) |
| `READ_LIGHT` | `LIGHT:350.0` | 照度 (lux) |
| `READ_DHT` | `DHT:25.3,60.2` | 温度,湿度 |
| `READ_ALL` | `SOIL:512,480;WATER:1;DHT:25.3,60.2;LIGHT:350.0;PUMP:OFF` | 一括取得 |
| `PUMP_ON` | `OK:PUMP_ON` or `ERR:NO_WATER` | ポンプ起動 |
| `PUMP_OFF` | `OK:PUMP_OFF` | ポンプ停止 |
| `STATUS_PUMP` | `PUMP:ON` or `PUMP:OFF` | ポンプ状態確認 |

### 安全機能 (Arduino 側にハードコード)

| 機能 | 内容 |
|------|------|
| ポンプ自動OFF | PUMP_ON 後 60秒で自動停止 |
| 水位不足ガード | 水位0のとき PUMP_ON を拒否 |
| 給水中水位監視 | 給水中に水がなくなったら即停止 |
| ウォッチドッグ | 通信途絶 5分でポンプ停止 |

## データ可視化

グラフは `raspi/graphs/` に自動生成されます (デフォルト: 6時間ごと)。

生成されるグラフ:
1. **dashboard.png** - 全センサー統合ダッシュボード (4パネル)
2. **soil_moisture.png** - 土壌湿度推移 (2系列 + 閾値ライン)
3. **climate.png** - 温度・湿度推移 (2軸)
4. **light.png** - 照度推移

Discord 通知が有効なら、グラフ生成時に自動で送信されます。

## 開発・テスト (実機なし)

```bash
# 依存インストール
pip install -r raspi/requirements.txt

# ターミナル1: モック Arduino 起動
cd raspi/tests && python mock_arduino.py

# ターミナル2: テスト実行
cd raspi && python tests/test_serial.py --port /tmp/mock_arduino
```

モック操作コマンド:
- `water_empty` / `water_full` - 水位変更
- `dry` / `wet` - 土壌湿度変更
- `bright` / `dark` - 照度変更

テスト結果: **9/9 テスト全パス** (PING, VERSION, READ_SOIL, READ_WATER, READ_LIGHT, READ_DHT, READ_ALL, PUMP_CYCLE, NO_WATER_SAFETY)

## 言語選定

### Arduino: C++ (Arduino C++)

「一度書き込んだら変更しない最小ドライバ」という設計のため、
エコシステムが最も充実した C++ を採用。
Rust (AVR) / Go (TinyGo) は Arduino のドライバ用途ではオーバースペック。

### Raspberry Pi: Python

変更頻度が高い制御ロジック側には柔軟性・開発速度を重視して Python を採用。
Google Sheets API、Discord 連携等のライブラリも豊富。

## 実装ロードマップ

- [x] **Phase 1-a**: Arduino ファームウェア + シリアルドライバ + テストツール
- [x] **Phase 1-b**: 給水判定ロジック + スケジューラ + 設定管理
- [x] **Phase 1-b**: Google Spreadsheet 連携 (設定読取 / ログ書込 / 手動給水)
- [x] **Phase 2**: Discord 通知 (給水レポート / 水不足アラート / エラー / グラフ送信)
- [x] **Phase 3**: データ可視化 (CSV ログ + matplotlib グラフ生成)
- [x] **Phase 3**: 照度センサー追加 (LDR, Arduino FW v1.0.0 → v1.1.0)
- [ ] **Phase 4**: Webダッシュボード + 天気API + USBカメラ

詳細な設計は [docs/system_design.md](docs/system_design.md) を参照。

## モロヘイヤ栽培アドバイザー

ECセンサーと各種環境センサーを組み合わせて、モロヘイヤの栽培状態を自動診断します。

### モロヘイヤの最適条件

| パラメータ | 最適範囲 | 備考 |
|-----------|---------|------|
| 気温 | 20〜35°C | 耐暑性高い。15°C以下で生育停滞 |
| 日照 | 25,000 lux以上 (直射日光) | 日陰では育たない。1日6時間以上必要 |
| 土壌 EC | 0.5〜2.0 mS/cm | 肥料濃度の指標。低すぎると栄養不足 |
| 土壌湿度 | 400〜700 | 過湿は根腐れの原因 |
| 空気湿度 | 50〜75% | 85%以上で病害リスク |

### 肥料管理 (EC値による判断)

| EC値 (mS/cm) | 状態 | アクション |
|-------------|------|----------|
| < 0.3 | 肥料不足 | 化成肥料 (8-8-8) または液肥を追肥 |
| 0.3〜0.5 | やや不足 | 追肥を検討。葉が小さい・色が薄い場合は窒素不足 |
| 0.5〜2.0 | 最適 | 現状維持 |
| 2.0〜3.0 | やや過多 | 追肥を控え、水やりで薄める |
| > 3.0 | 塩害リスク | たっぷりの水で土壌を洗い流す (リーチング) |

### 診断出力例 (Discord通知)

```
🌿 モロヘイヤ 栽培診断 (スコア: 85/100)
✅ 気温: 28.5°C - 最適範囲です。
✅ 日照: 35000 lux - 十分な日照です。
⚠️ EC (肥料濃度): 0.45 mS/cm - やや肥料が薄い。追肥を検討。
✅ 土壌湿度: 500 - 適切な湿度です。
✅ 空気湿度: 60.0% - 良好。
☀ 天気: 24時間以内の雨なし / 日照10.5時間
```

### 天気API連携

Open-Meteo (無料, APIキー不要) を使用:
- **雨予報で給水スキップ**: 6時間以内に2mm以上の降水予報 → 自動的に給水を見送り
- **日照時間予報**: モロヘイヤの日当たり評価に活用
- **気温予報**: 低温警告や高温対策のアドバイス
- config.yaml で緯度・経度を設定可能 (デフォルト: 東京)
