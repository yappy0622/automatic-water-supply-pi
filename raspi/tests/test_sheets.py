"""
test_sheets.py - Sheets 書き込み整形のテスト
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from raspi.external.sheets import SheetsClient


class FakeWorksheet:
    def __init__(self):
        self.rows = []

    def append_row(self, row, value_input_option=None):
        self.rows.append(row)


def test_watering_log_leaves_after_moisture_blank_when_skipped():
    client = object.__new__(SheetsClient)
    worksheet = FakeWorksheet()
    client._sheets_cache = {"watering_log": worksheet}
    client._api_call_with_retry = lambda func, *args, **kwargs: func(*args, **kwargs)

    client.append_watering_log(
        trigger="PERIODIC",
        soil_before=[0.71],
        pump_duration=0,
        soil_after=[],
        result="SKIPPED: 土壌湿度十分",
    )

    assert worksheet.rows[0][2] == "0.71"
    assert worksheet.rows[0][4] == ""
