"""
sheets.py - Google Spreadsheet 連携

スマホ ⇄ Spreadsheet ⇄ ラズパイ の橋渡し。

機能:
  1. 「設定」シートを読み取り → ConfigManager にマージ (スマホからの閾値変更等)
  2. 「センサーログ」シートにセンサーデータを追記
  3. 「給水履歴」シートに給水結果を追記
  4. 「設定」シートの手動給水フラグを読み取り/リセット

セットアップ手順:
  1. Google Cloud Console でプロジェクト作成
  2. Google Sheets API を有効化
  3. サービスアカウントを作成し、JSONキーをダウンロード
  4. キーファイルを raspi/credentials.json に配置
  5. スプレッドシートをサービスアカウントのメールアドレスに共有
  6. config.yaml の google_sheets セクションを設定
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import gspread
    from google.oauth2.service_account import Credentials

    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.info("gspread がインストールされていません。Sheets連携は無効です。")


# Spreadsheet「設定」シートのセルマッピング
# A列=項目名, B列=値
SETTINGS_CELL_MAP = {
    "B2": "soil_threshold",      # 土壌湿度閾値 (0.0〜1.0)
    "B3": "pump_duration",       # 給水時間(秒)
    "B4": "watering_time",       # スケジュール時刻
    "B5": "mode",                # 給水モード (AUTO/MANUAL/OFF)
    "B6": "manual_trigger",      # 手動給水指示 (TRUE/FALSE)
    "B7": "notification_enabled", # 通知ON/OFF
    # センサーキャリブレーション (B8-B11)
    "B8": "sensor1_dry",         # センサ1 乾燥時の生値
    "B9": "sensor1_wet",         # センサ1 湿潤時の生値
    "B10": "sensor2_dry",        # センサ2 乾燥時の生値
    "B11": "sensor2_wet",        # センサ2 湿潤時の生値
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class SheetsClient:
    """Google Spreadsheet クライアント"""

    def __init__(
        self,
        credentials_file: str,
        spreadsheet_id: str,
        sheet_settings: str = "設定",
        sheet_sensor_log: str = "センサーログ",
        sheet_watering_log: str = "給水履歴",
    ):
        if not GSPREAD_AVAILABLE:
            raise ImportError(
                "gspread がインストールされていません。\n"
                "  pip install gspread google-auth"
            )

        self._credentials_file = credentials_file
        self._spreadsheet_id = spreadsheet_id
        self._sheet_names = {
            "settings": sheet_settings,
            "sensor_log": sheet_sensor_log,
            "watering_log": sheet_watering_log,
        }
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None

    def connect(self) -> None:
        """Spreadsheet に接続"""
        creds = Credentials.from_service_account_file(
            self._credentials_file, scopes=SCOPES
        )
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        
        # 起動時にワークシートをキャッシュ
        self._sheets_cache: dict[str, gspread.Worksheet] = {
            key: self._spreadsheet.worksheet(name)
            for key, name in self._sheet_names.items()
        }
        logger.info(f"Spreadsheet 接続完了: {self._spreadsheet.title}")

    def _get_sheet(self, key: str) -> "gspread.Worksheet":
        """キャッシュからワークシートを返す"""
        if not hasattr(self, "_sheets_cache"):
            raise RuntimeError("Spreadsheet に未接続です。connect() を先に呼んでください。")
        try:
            return self._sheets_cache[key]
        except KeyError:
            raise RuntimeError(f"シートキー '{key}' が見つかりません")
        except Exception:
            # セッション切れの場合は再接続
            logger.warning("ワークシートキャッシュ無効、再接続します")
            self.connect()
            return self._sheets_cache[key]

    # =========================================================================
    # 1. 設定の読み取り (スマホ → ラズパイ)
    # =========================================================================

    def read_settings(self) -> dict:
        try:
            ws = self._get_sheet("settings")
            
            # B2:B11 を1回のAPIコールで一括取得
            cell_range = self._api_call_with_retry(ws.get, "B2:B11")
            
            result = {}
            cell_addrs = list(SETTINGS_CELL_MAP.keys())  # ["B2", "B3", ...]
            keys = list(SETTINGS_CELL_MAP.values())       # ["soil_threshold", ...]
            
            for i, key in enumerate(keys):
                try:
                    value = cell_range[i][0] if i < len(cell_range) and cell_range[i] else None
                except IndexError:
                    value = None
                if value is not None and str(value).strip() != "":
                    result[key] = value
            
            logger.debug(f"Sheets 設定読み取り: {result}")
            return result
        except Exception as e:
            logger.error(f"Sheets 設定読み取りエラー: {e}", exc_info=True)
            return {}

    def reset_manual_trigger(self) -> None:
        """「設定」シートの手動給水フラグを FALSE にリセット"""
        try:
            ws = self._get_sheet("settings")
            ws.update_acell("B6", "FALSE")
            logger.info("手動給水フラグをリセットしました")
        except Exception as e:
            logger.error(f"手動給水フラグリセットエラー: {e}")

    # =========================================================================
    # 2. センサーログ書き込み (ラズパイ → スマホ)
    # =========================================================================

    def append_sensor_log(
        self,
        soil_values: list[int],
        water_ok: bool,
        temperature: Optional[float],
        humidity: Optional[float],
        pump_status: str = "--",
        note: str = "",
    ) -> None:
        """
        「センサーログ」シートに1行追記。

        列構成: タイムスタンプ | 土壌1 | 土壌2 | 水位 | 温度 | 湿度 | ポンプ | 備考
        """
        try:
            ws = self._get_sheet("sensor_log")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now,
                f"{soil_values[0]:.2f}" if len(soil_values) > 0 else "",  # :.2f に変更
                f"{soil_values[1]:.2f}" if len(soil_values) > 1 else "",  # :.2f に変更
                "1" if water_ok else "0",
                f"{temperature:.1f}" if temperature is not None else "ERR",
                f"{humidity:.1f}" if humidity is not None else "ERR",
                pump_status,
                note,
            ]
            self._api_call_with_retry(ws.append_row, row, value_input_option="USER_ENTERED")
            logger.debug(f"センサーログ追記: {row}")
        except Exception as e:
            logger.error(f"センサーログ書き込みエラー: {e}", exc_info=True) 

    # =========================================================================
    # 3. 給水履歴書き込み (ラズパイ → スマホ)
    # =========================================================================

    def append_watering_log(
        self,
        trigger: str,
        soil_before: list[int],
        pump_duration: int,
        soil_after: list[int],
        result: str,
    ) -> None:
        """
        「給水履歴」シートに1行追記。

        列構成: タイムスタンプ | トリガー | 給水前湿度 | 給水時間(秒) | 給水後湿度 | 結果
        """
        try:
            ws = self._get_sheet("watering_log")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            avg_before = sum(soil_before) / len(soil_before) if soil_before else None
            avg_after = sum(soil_after) / len(soil_after) if soil_after else None

            row = [
                now,
                trigger,
                f"{avg_before:.2f}" if avg_before is not None else "",
                str(pump_duration),
                f"{avg_after:.2f}" if avg_after is not None else "",
                result,
            ]
            self._api_call_with_retry(ws.append_row, row, value_input_option="USER_ENTERED")
            before_text = f"{avg_before:.2f}" if avg_before is not None else "--"
            after_text = f"{avg_after:.2f}" if avg_after is not None else "--"
            logger.info(f"給水履歴追記: {trigger} / {before_text}→{after_text} / {result}")
        except Exception as e:
            logger.error(f"給水履歴書き込みエラー: {e}")

    def _api_call_with_retry(self, func, *args, **kwargs):
        """API呼び出しを失敗時に1回再接続してリトライする"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"API呼び出し失敗、再接続してリトライ: {e}")
            try:
                self.connect()
                return func(*args, **kwargs)
            except Exception as e2:
                raise e2
