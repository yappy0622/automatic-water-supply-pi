"""
watering.py - 給水判定・実行ロジック

設計書 Section 7 のフローを実装。
Arduino ドライバと設定マネージャを受け取り、給水判定→実行→記録を行う。
"""

import time
import logging
from typing import Optional

from raspi.arduino.serial_driver import (
    ArduinoDriver,
    ArduinoNoWaterError,
    ArduinoError,
    SensorReadAll,
)
from raspi.config_manager import AppConfig
from raspi.external.sheets import SheetsClient

logger = logging.getLogger(__name__)


class WateringResult:
    """給水実行の結果"""

    def __init__(self):
        self.executed: bool = False
        self.trigger: str = ""           # "AUTO" / "MANUAL"
        self.soil_before: list[int] = []
        self.soil_after: list[int] = []
        self.pump_duration: int = 0
        self.success: bool = False
        self.message: str = ""
        self.skipped_reason: str = ""    # 給水しなかった理由


class WateringController:
    """
    給水制御コントローラ

    全判定ロジックはここに集約。Arduino は言われたとおりに動くだけ。
    """

    def __init__(
        self,
        arduino: ArduinoDriver,
        config: AppConfig,
        sheets: Optional[SheetsClient] = None,
    ):
        self._arduino = arduino
        self._config = config
        self._sheets = sheets

    # =========================================================================
    # メイン: 給水判定 → 実行
    # =========================================================================

    def check_and_water(self, trigger: str = "AUTO") -> WateringResult:
        """
        給水判定を行い、必要であれば給水を実行する。

        Args:
            trigger: "AUTO" (スケジュール) or "MANUAL" (手動指示)

        Returns:
            WateringResult
        """
        result = WateringResult()
        result.trigger = trigger
        wc = self._config.watering

        logger.info(f"=== 給水判定開始 (trigger={trigger}, mode={wc.mode}) ===")

        # --- モードチェック ---
        if wc.mode == "OFF":
            result.skipped_reason = "給水モード OFF"
            logger.info(f"スキップ: {result.skipped_reason}")
            return result

        if wc.mode == "MANUAL" and trigger == "AUTO":
            result.skipped_reason = "MANUAL モードのためスケジュール給水はスキップ"
            logger.info(f"スキップ: {result.skipped_reason}")
            return result

        # --- センサー読み取り ---
        try:
            sensor_data = self._arduino.read_all()
        except ArduinoError as e:
            result.skipped_reason = f"センサー読み取り失敗: {e}"
            logger.error(result.skipped_reason)
            self._log_sensor_to_sheets(None, note=f"ERR: {e}")
            return result

        result.soil_before = sensor_data.soil
        avg_moisture = sum(sensor_data.soil) / len(sensor_data.soil) if sensor_data.soil else 0

        logger.info(
            f"センサー値: 土壌={sensor_data.soil} (平均={avg_moisture:.0f}), "
            f"水位={'OK' if sensor_data.water_ok else 'NG'}, "
            f"温度={sensor_data.temperature}, 湿度={sensor_data.humidity}"
        )

        # センサーログ記録
        self._log_sensor_to_sheets(sensor_data)

        # --- 手動給水: 閾値判定をスキップして即給水 ---
        if trigger == "MANUAL":
            logger.info("手動給水: 閾値判定をスキップ")
        else:
            # --- 土壌湿度判定 ---
            if avg_moisture >= wc.soil_threshold:
                result.skipped_reason = (
                    f"土壌湿度十分 (平均={avg_moisture:.0f} >= 閾値={wc.soil_threshold})"
                )
                logger.info(f"給水不要: {result.skipped_reason}")
                return result

            logger.info(
                f"乾燥検知: 平均={avg_moisture:.0f} < 閾値={wc.soil_threshold} → 給水実行"
            )

        # --- 水位チェック ---
        if not sensor_data.water_ok:
            result.skipped_reason = "給水タンクの水が不足しています"
            logger.warning(f"給水中止: {result.skipped_reason}")
            self._log_sensor_to_sheets(sensor_data, note="ALERT: 水不足")
            return result

        # --- 給水実行 ---
        result.executed = True
        result.pump_duration = wc.pump_duration

        try:
            self._execute_pump(wc.pump_duration)
        except ArduinoNoWaterError:
            result.success = False
            result.message = "Arduino 側で水不足検知 (ERR:NO_WATER)"
            logger.error(result.message)
            self._log_watering_to_sheets(result)
            return result
        except ArduinoError as e:
            result.success = False
            result.message = f"ポンプ制御エラー: {e}"
            logger.error(result.message)
            # 安全のため OFF を試みる
            try:
                self._arduino.pump_off()
            except ArduinoError:
                pass
            self._log_watering_to_sheets(result)
            return result

        # --- 給水後の確認 ---
        logger.info(f"給水後待機中... ({wc.post_watering_wait}秒)")
        time.sleep(wc.post_watering_wait)

        try:
            soil_after = self._arduino.read_soil()
            result.soil_after = soil_after
            avg_after = sum(soil_after) / len(soil_after) if soil_after else 0
            logger.info(f"給水後の土壌湿度: {soil_after} (平均={avg_after:.0f})")

            # 湿度が上がっていれば成功
            result.success = avg_after > avg_moisture
            if result.success:
                result.message = f"給水成功: {avg_moisture:.0f} → {avg_after:.0f}"
            else:
                result.message = f"給水したが湿度上昇なし: {avg_moisture:.0f} → {avg_after:.0f}"
                logger.warning(result.message)

        except ArduinoError as e:
            logger.warning(f"給水後のセンサー読み取り失敗: {e}")
            result.success = True  # ポンプは動いたので一応成功扱い
            result.message = f"給水完了 (後確認失敗: {e})"

        logger.info(f"=== 給水判定完了: {result.message} ===")

        # 記録
        self._log_sensor_to_sheets(None, pump_status="ON", note=result.message)
        self._log_watering_to_sheets(result)

        return result

    # =========================================================================
    # ポンプ操作
    # =========================================================================

    def _execute_pump(self, duration: int) -> None:
        """ポンプを指定秒数ONにして停止する"""
        logger.info(f"ポンプ ON ({duration}秒間)")
        self._arduino.pump_on()

        time.sleep(duration)

        logger.info("ポンプ OFF")
        self._arduino.pump_off()

    def emergency_stop(self) -> None:
        """緊急停止"""
        logger.warning("緊急停止: ポンプ OFF")
        try:
            self._arduino.pump_off()
        except ArduinoError as e:
            logger.error(f"緊急停止に失敗: {e}")

    # =========================================================================
    # Spreadsheet 記録 (オプション)
    # =========================================================================

    def _log_sensor_to_sheets(
        self,
        data: Optional[SensorReadAll],
        pump_status: str = "--",
        note: str = "",
    ) -> None:
        """センサーデータを Spreadsheet に記録 (有効な場合のみ)"""
        if self._sheets is None:
            return
        try:
            if data:
                self._sheets.append_sensor_log(
                    soil_values=data.soil,
                    water_ok=data.water_ok,
                    temperature=data.temperature,
                    humidity=data.humidity,
                    pump_status=pump_status,
                    note=note,
                )
            elif note:
                self._sheets.append_sensor_log(
                    soil_values=[],
                    water_ok=False,
                    temperature=None,
                    humidity=None,
                    pump_status=pump_status,
                    note=note,
                )
        except Exception as e:
            logger.error(f"Sheets センサーログ記録失敗: {e}")

    def _log_watering_to_sheets(self, result: WateringResult) -> None:
        """給水結果を Spreadsheet に記録 (有効な場合のみ)"""
        if self._sheets is None:
            return
        try:
            self._sheets.append_watering_log(
                trigger=result.trigger,
                soil_before=result.soil_before,
                pump_duration=result.pump_duration,
                soil_after=result.soil_after,
                result="SUCCESS" if result.success else "FAIL",
            )
        except Exception as e:
            logger.error(f"Sheets 給水履歴記録失敗: {e}")
