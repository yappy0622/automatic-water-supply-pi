"""
test_scheduled_logging.py - スケジュール給水判定時の Sheets ログテスト
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from raspi.arduino.serial_driver import SensorReadAll
from raspi.config_manager import AppConfig
from raspi.logic.watering import WateringController


class FakeArduino:
    def read_all(self):
        return SensorReadAll(
            soil=[1023, 1023],
            water_ok=True,
            temperature=24.0,
            humidity=55.0,
            pump_running=False,
        )


class FakeSheets:
    def __init__(self):
        self.sensor_logs = []
        self.watering_logs = []

    def append_sensor_log(self, **kwargs):
        self.sensor_logs.append(kwargs)

    def append_watering_log(self, **kwargs):
        self.watering_logs.append(kwargs)


def test_scheduled_check_logs_sensor_and_watering_history_when_skipped():
    config = AppConfig()
    sheets = FakeSheets()
    controller = WateringController(
        arduino=FakeArduino(),
        config=config,
        sheets=sheets,
    )

    result = controller.check_and_water(trigger="AUTO")

    assert result.executed is False
    assert len(sheets.sensor_logs) == 1
    assert len(sheets.watering_logs) == 1
    assert sheets.watering_logs[0]["trigger"] == "AUTO"
    assert sheets.watering_logs[0]["result"].startswith("SKIPPED: 土壌湿度十分")
