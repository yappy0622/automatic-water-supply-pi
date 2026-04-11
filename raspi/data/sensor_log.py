"""
sensor_log.py - ローカル CSV センサーログ

Spreadsheet が落ちていても、ローカルにセンサーデータを蓄積する。
grapher.py がこの CSV を読み込んでグラフを生成する。

CSV フォーマット:
  timestamp, soil_1, soil_2, water_ok, temperature, humidity, light_lux, ec, pump, note

使用例:
    csv_logger = SensorCSVLogger()
    csv_logger.append(sensor_data)
    csv_logger.append_watering(result)
"""

import os
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# デフォルトのログディレクトリとファイル名
DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
DEFAULT_CSV_NAME = "sensor_data.csv"

CSV_HEADER = [
    "timestamp",
    "soil_1",
    "soil_2",
    "water_ok",
    "temperature",
    "humidity",
    "light_lux",
    "ec",
    "pump",
    "note",
]


class SensorCSVLogger:
    """ローカル CSV にセンサーデータを追記するロガー"""

    def __init__(
        self,
        log_dir: str = DEFAULT_LOG_DIR,
        filename: str = DEFAULT_CSV_NAME,
    ):
        self._log_dir = log_dir
        self._csv_path = os.path.join(log_dir, filename)

        # ログディレクトリ作成
        os.makedirs(log_dir, exist_ok=True)

        # ヘッダー行の書き込み (ファイルが存在しない or 空の場合)
        self._ensure_header()

    @property
    def csv_path(self) -> str:
        return self._csv_path

    def _ensure_header(self) -> None:
        """CSV ファイルにヘッダーが無ければ書き込む"""
        need_header = True
        if os.path.exists(self._csv_path):
            with open(self._csv_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    need_header = False

        if need_header:
            with open(self._csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADER)
            logger.info(f"CSV ログファイル作成: {self._csv_path}")

    def append(
        self,
        sensor_data,
        pump_status: str = "--",
        note: str = "",
    ) -> None:
        """
        SensorReadAll データを CSV に追記。

        Args:
            sensor_data: ArduinoDriver.read_all() の戻り値 (SensorReadAll)
            pump_status: ポンプ状態文字列 ("ON", "OFF", "--")
            note: 備考
        """
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            soil_1 = sensor_data.soil[0] if len(sensor_data.soil) > 0 else ""
            soil_2 = sensor_data.soil[1] if len(sensor_data.soil) > 1 else ""
            temp = f"{sensor_data.temperature:.1f}" if sensor_data.temperature is not None else ""
            hum = f"{sensor_data.humidity:.1f}" if sensor_data.humidity is not None else ""
            light = (
                f"{sensor_data.light_lux:.0f}"
                if hasattr(sensor_data, "light_lux") and sensor_data.light_lux is not None
                else ""
            )
            ec = (
                f"{sensor_data.ec_value:.2f}"
                if hasattr(sensor_data, "ec_value") and sensor_data.ec_value is not None
                else ""
            )

            row = [
                now,
                soil_1,
                soil_2,
                "1" if sensor_data.water_ok else "0",
                temp,
                hum,
                light,
                ec,
                pump_status,
                note,
            ]

            with open(self._csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)

            logger.debug(f"CSV 追記: {row}")

        except Exception as e:
            logger.error(f"CSV 書き込みエラー: {e}")

    def append_raw(
        self,
        soil_values: list[int],
        water_ok: bool,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        light_lux: Optional[float] = None,
        ec_value: Optional[float] = None,
        pump_status: str = "--",
        note: str = "",
    ) -> None:
        """生の値から CSV に追記 (SensorReadAll 以外からの利用向け)"""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now,
                soil_values[0] if len(soil_values) > 0 else "",
                soil_values[1] if len(soil_values) > 1 else "",
                "1" if water_ok else "0",
                f"{temperature:.1f}" if temperature is not None else "",
                f"{humidity:.1f}" if humidity is not None else "",
                f"{light_lux:.0f}" if light_lux is not None else "",
                f"{ec_value:.2f}" if ec_value is not None else "",
                pump_status,
                note,
            ]
            with open(self._csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"CSV 書き込みエラー: {e}")

    def row_count(self) -> int:
        """ヘッダーを除く行数を返す"""
        if not os.path.exists(self._csv_path):
            return 0
        with open(self._csv_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f) - 1  # ヘッダー除外
