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


def normalize_sensor_value(raw_value: int, dry: int, wet: int) -> float:
    """
    センサー値を0-1の範囲に正規化する。

    乾燥・湿潤の大小関係が逆でも正しく動作する:
    - 乾燥値 > 湿潤値 の場合 (一般的なセンサー): dry=442, wet=297 → 乾燥=1.0, 湿潤=0.0
    - 乾燥値 < 湿潤値 の場合: dry=5, wet=47 → 乾燥=0.0, 湿潤=1.0

    Args:
        raw_value: センサーの生値
        dry: 乾燥時の実測値
        wet: 湿潤時の実測値

    Returns:
        正規化された湿度 (0.0=乾燥, 1.0=湿潤)
    """
    if dry == wet:
        return 0.5  # ゼロ除算防止

    # 線形補間で0-1に正規化
    normalized = (raw_value - dry) / (wet - dry)

    # 0-1の範囲にクランプ
    return max(0.0, min(1.0, normalized))


class WateringResult:
    """給水実行の結果"""

    def __init__(self):
        self.executed: bool = False
        self.trigger: str = ""
        self.soil_before: list[int] = []
        self.soil_after: list[int] = []
        self.soil_before_normalized: list[float] = []
        self.soil_after_normalized: list[float] = []
        self.pump_duration: int = 0
        self.success: bool = False
        self.message: str = ""
        self.skipped_reason: str = ""


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
        result.soil_before_normalized = calibrated
        
        # --- センサーキャリブレーション ---
        # 各センサー値を正規化 (0.0=乾燥, 1.0=湿潤)
        calibrated = []
        # センサー設定をリスト化する場合
        params = [
            (wc.sensor1_dry, wc.sensor1_wet),
            (wc.sensor2_dry, wc.sensor2_wet),
        ]

        for raw, (dry, wet) in zip(sensor_data.soil, params):
            calibrated.append(normalize_sensor_value(raw, dry, wet))
        
        avg_moisture = sum(calibrated) / len(calibrated) if calibrated else 0
        min_moisture = min(calibrated) if calibrated else 0

        logger.info(
            f"センサー値: 生値={sensor_data.soil} → 正規化={calibrated} "
            f"(avg={avg_moisture:.2f}, min={min_moisture:.2f}), "
            f"水位={'OK' if sensor_data.water_ok else 'NG'}, "
            f"温度={sensor_data.temperature}, 湿度={sensor_data.humidity}"
        )

        # センサーログ記録
        self._log_sensor_to_sheets(sensor_data, calibrated=calibrated)

        # --- 手動給水: 閾値判定をスキップして即給水 ---
        if trigger == "MANUAL":
            logger.info("手動給水: 閾値判定をスキップ")
        else:
            # --- 土壌湿度判定 ---
            # soil_threshold は 0.0〜1.0 の正規化済み値
            threshold = wc.soil_threshold          # 例: 0.35（乾燥寄り）
            critical = wc.soil_critical_threshold # 例: 0.15（安全ライン）

            # 危険な乾燥 → 即給水
            if min_moisture < critical:
                logger.warning(
                    f"危険乾燥検知: min={min_moisture:.2f} < {critical:.2f} → 強制給水"
                )

            # 通常判定（トマト向け：平均で乾燥維持）
            elif avg_moisture >= threshold:
                result.skipped_reason = (
                    f"土壌湿度十分 (avg={avg_moisture:.2f} >= {threshold:.2f})"
                )
                logger.info(f"給水不要: {result.skipped_reason}")
                return result

            else:
                logger.info(
                    f"乾燥検知: avg={avg_moisture:.2f} < {threshold:.2f} → 給水"
                )

        # --- 水位チェック ---
        if not sensor_data.water_ok:
            result.skipped_reason = "給水タンクの水が不足しています"
            logger.warning(f"給水中止: {result.skipped_reason}")
            self._log_sensor_to_sheets(sensor_data, note="ALERT: 水不足", calibrated=calibrated)
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
            soil_after_raw = self._arduino.read_soil()
            result.soil_after = soil_after_raw
            result.soil_after_normalized = calibrated_after
            
            # 給水後の値も正規化
            calibrated_after = [
                normalize_sensor_value(raw, dry, wet)
                for raw, (dry, wet) in zip(soil_after_raw, params)
            ]
            
            avg_after = sum(calibrated_after) / len(calibrated_after) if calibrated_after else 0
            logger.info(f"給水後の土壌湿度: 生値={soil_after_raw} → 正規化={calibrated_after} (平均={avg_after:.2f})")

            # 湿度が上がっていれば成功
            delta = avg_after - avg_moisture
            result.success = delta > wc.success_moisture_delta  # 0.02以上の上昇があれば成功とみなす (要調整)
            if result.success:
                result.message = f"給水成功: {avg_moisture:.2f} → {avg_after:.2f}"
            else:
                result.message = f"給水したが湿度上昇なし: {avg_moisture:.2f} → {avg_after:.2f}"
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
        logger.info(f"ポンプ ON ({duration}秒間)")
        self._arduino.pump_on()
        try:
            time.sleep(duration)
        finally:
            logger.info("ポンプ OFF")
            self._arduino.pump_off()  # 必ず止める

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
        calibrated: Optional[list[float]] = None,
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
        if self._sheets is None:
            return
        try:
            self._sheets.append_watering_log(
                trigger=result.trigger,
                soil_before=result.soil_before_normalized,  # 正規化済みに変更
                pump_duration=result.pump_duration,
                soil_after=result.soil_after_normalized,    # 正規化済みに変更
                result="SUCCESS" if result.success else "FAIL",
            )
        except Exception as e:
            logger.error(f"Sheets 給水履歴記録失敗: {e}")