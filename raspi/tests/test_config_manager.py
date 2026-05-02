"""
test_config_manager.py - 設定マージのテスト
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config_manager import ConfigManager


def test_sheets_watering_time_is_zero_padded():
    manager = ConfigManager(config_path="/tmp/does-not-exist-config.yaml")

    manager.merge_sheets_settings({"watering_time": "7:00, 19:00"})

    assert manager.config.schedule.watering_times == ["07:00", "19:00"]


def test_sheets_watering_time_ignores_invalid_entries():
    manager = ConfigManager(config_path="/tmp/does-not-exist-config.yaml")

    manager.merge_sheets_settings({"watering_time": "bad, 7:00"})

    assert manager.config.schedule.watering_times == ["07:00"]
