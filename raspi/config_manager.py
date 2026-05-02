"""
config_manager.py - 設定管理

設定の優先順位:
  1. Google Spreadsheet「設定」シート (リアルタイム、スマホから変更可能)
  2. ローカル config.yaml (デフォルト値、Sheets が無効/接続不能時のフォールバック)

Spreadsheet の設定はポーリングで定期的に取得し、ローカル設定にマージする。
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from copy import deepcopy

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")


@dataclass
class ArduinoConfig:
    port: str = "/dev/ttyUSB0"
    baud_rate: int = 9600
    timeout: float = 2.0
    max_retries: int = 3


@dataclass
class WateringConfig:
    soil_threshold: float = 0.4 # この値以下で「乾燥」と判定 (0.0=乾燥, 1.0=湿潤)
    scheduled_watering_threshold: float = 0.95 # スケジュール給水時の閾値
    soil_critical_threshold: float = 0.15  # 追加
    success_moisture_delta: float = 0.02   # 追加
    pump_duration: int = 10
    post_watering_wait: int = 30
    mode: str = "AUTO"
    # センサーキャリブレーション
    sensor1_dry: int = 0
    sensor1_wet: int = 1023
    sensor2_dry: int = 0
    sensor2_wet: int = 1023


@dataclass
class ScheduleConfig:
    watering_times: list[str] = field(default_factory=lambda: ["07:00", "19:00"])
    sensor_interval_min: int = 30
    sheets_poll_interval_min: int = 5


@dataclass
class GoogleSheetsConfig:
    enabled: bool = False
    credentials_file: str = "credentials.json"
    spreadsheet_id: str = ""
    sheet_settings: str = "設定"
    sheet_sensor_log: str = "センサーログ"
    sheet_watering_log: str = "給水履歴"


@dataclass
class NotificationConfig:
    discord_webhook_url: str = ""
    notify_on_watering: bool = True
    notify_on_low_water: bool = True
    notify_on_error: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/watering.log"
    max_bytes: int = 5242880
    backup_count: int = 3


@dataclass
class AppConfig:
    """アプリケーション全体の設定"""
    arduino: ArduinoConfig = field(default_factory=ArduinoConfig)
    watering: WateringConfig = field(default_factory=WateringConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


class ConfigManager:
    """
    設定マネージャ

    ローカル YAML を読み込み、Spreadsheet の設定でマージする。
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = config_path
        self._config = AppConfig()
        self.load_local()

    @property
    def config(self) -> AppConfig:
        return self._config

    # --- ローカル YAML ---

    def load_local(self) -> None:
        """ローカル config.yaml を読み込む"""
        if not os.path.exists(self._config_path):
            logger.warning(f"設定ファイルが見つかりません: {self._config_path} (デフォルト値を使用)")
            return

        with open(self._config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        self._apply_dict(raw)
        logger.info(f"ローカル設定を読み込みました: {self._config_path}")

    def _apply_dict(self, raw: dict) -> None:
        """辞書から各設定セクションに値を適用"""
        if "arduino" in raw:
            self._update_dataclass(self._config.arduino, raw["arduino"])
        if "watering" in raw:
            self._update_dataclass(self._config.watering, raw["watering"])
        if "schedule" in raw:
            self._update_dataclass(self._config.schedule, raw["schedule"])
        if "google_sheets" in raw:
            self._update_dataclass(self._config.google_sheets, raw["google_sheets"])
        if "notification" in raw:
            self._update_dataclass(self._config.notification, raw["notification"])
        if "logging" in raw:
            self._update_dataclass(self._config.logging, raw["logging"])

    @staticmethod
    def _update_dataclass(dc: object, values: dict) -> None:
        """dataclass のフィールドを辞書の値で更新 (存在するキーのみ)"""
        for key, value in values.items():
            if hasattr(dc, key) and value is not None:
                setattr(dc, key, value)

    @staticmethod
    def _normalize_watering_time(value: object) -> Optional[str]:
        """給水時刻をスケジュール比較用の HH:MM 形式にそろえる"""
        text = str(value).strip()
        if not text:
            return None

        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).strftime("%H:%M")
            except ValueError:
                continue

        logger.warning(f"[Sheets] 無効なスケジュール時刻を無視: {text}")
        return None

    # --- Spreadsheet からの設定マージ ---

    def merge_sheets_settings(self, sheets_data: dict) -> None:
        """
        Spreadsheet「設定」シートから取得した値でローカル設定を上書きする。

        sheets_data のキー名は Spreadsheet のセル項目名に対応:
            {
                "soil_threshold": 400,
                "pump_duration": 10,
                "watering_time": "07:00",
                "mode": "AUTO",
                "manual_trigger": False,
                "notification_enabled": True,
            }
        """
        w = self._config.watering
        s = self._config.schedule

        if "soil_threshold" in sheets_data:
            try:
                w.soil_threshold = float(sheets_data["soil_threshold"])
                logger.info(f"[Sheets] 土壌湿度閾値 → {w.soil_threshold}")
            except (ValueError, TypeError):
                pass

        if "pump_duration" in sheets_data:
            try:
                w.pump_duration = int(sheets_data["pump_duration"])
                logger.info(f"[Sheets] 給水時間 → {w.pump_duration}秒")
            except (ValueError, TypeError):
                pass

        if "watering_time" in sheets_data:
            time_str = str(sheets_data["watering_time"]).strip()
            if time_str:
                watering_times = [
                    normalized
                    for t in time_str.split(",")
                    if (normalized := self._normalize_watering_time(t))
                ]
                if watering_times:
                    s.watering_times = watering_times
                    logger.info(f"[Sheets] スケジュール → {s.watering_times}")

        if "mode" in sheets_data:
            mode = str(sheets_data["mode"]).strip().upper()
            if mode in ("AUTO", "MANUAL", "OFF"):
                w.mode = mode
                logger.info(f"[Sheets] 給水モード → {w.mode}")

        if "notification_enabled" in sheets_data:
            val = sheets_data["notification_enabled"]
            enabled = str(val).strip().upper() in ("TRUE", "1", "YES")
            self._config.notification.notify_on_watering = enabled
            self._config.notification.notify_on_low_water = enabled
            logger.info(f"[Sheets] 通知 → {'ON' if enabled else 'OFF'}")

        # センサーキャリブレーション
        for key in ("sensor1_dry", "sensor1_wet", "sensor2_dry", "sensor2_wet"):
            if key in sheets_data:
                try:
                    setattr(w, key, int(sheets_data[key]))
                    logger.info(f"[Sheets] {key} → {getattr(w, key)}")
                except (ValueError, TypeError):
                    pass

    def is_manual_trigger(self, sheets_data: dict) -> bool:
        """
        Spreadsheet で「手動給水」が指示されているかを判定。
        TRUE が書かれていれば True を返す。
        (読み取り後、sheets.py 側で FALSE にリセットする)
        """
        val = sheets_data.get("manual_trigger", False)
        return str(val).strip().upper() in ("TRUE", "1", "YES")
