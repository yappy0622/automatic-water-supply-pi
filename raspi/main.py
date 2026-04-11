#!/usr/bin/env python3
"""
main.py - 自動給水システム エントリポイント

以下のループを実行する:
  1. 定時になったら給水判定
  2. 定期的にセンサーデータを取得して記録
  3. Spreadsheet をポーリングして設定変更・手動給水指示を反映

使い方:
    # 通常起動 (config.yaml を読み込み)
    python main.py

    # 設定ファイルを指定
    python main.py --config /path/to/config.yaml

    # テスト: 即座に1回給水判定して終了
    python main.py --once
"""

import sys
import os
import time
import signal
import argparse
import logging
from datetime import datetime
from typing import Optional

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raspi.config_manager import ConfigManager
from raspi.data.logger import setup_logging
from raspi.arduino.serial_driver import ArduinoDriver, ArduinoError
from raspi.logic.watering import WateringController
from raspi.external.sheets import SheetsClient

logger = logging.getLogger(__name__)


class WateringSystem:
    """自動給水システム メインクラス"""

    def __init__(self, config_path: str):
        self._config_manager = ConfigManager(config_path)
        self._cfg = self._config_manager.config
        self._arduino: Optional[ArduinoDriver] = None
        self._sheets: Optional[SheetsClient] = None
        self._controller: Optional[WateringController] = None
        self._running = False

        # タイミング管理
        self._last_sensor_read = 0.0
        self._last_sheets_poll = 0.0
        self._last_watering_checks: set[str] = set()  # 今日チェック済みの時刻

    # =========================================================================
    # 起動・終了
    # =========================================================================

    def start(self) -> None:
        """システム起動"""
        cfg = self._cfg

        # ログ設定
        setup_logging(
            level=cfg.logging.level,
            log_file=cfg.logging.file,
            max_bytes=cfg.logging.max_bytes,
            backup_count=cfg.logging.backup_count,
        )

        logger.info("=" * 60)
        logger.info("自動給水システム 起動")
        logger.info("=" * 60)
        logger.info(f"給水モード : {cfg.watering.mode}")
        logger.info(f"土壌閾値   : {cfg.watering.soil_threshold}")
        logger.info(f"給水時間   : {cfg.watering.pump_duration}秒")
        logger.info(f"スケジュール: {cfg.schedule.watering_times}")
        logger.info(f"Sheets連携 : {'有効' if cfg.google_sheets.enabled else '無効'}")

        # Arduino 接続
        self._arduino = ArduinoDriver(
            port=cfg.arduino.port,
            baud_rate=cfg.arduino.baud_rate,
            timeout=cfg.arduino.timeout,
            max_retries=cfg.arduino.max_retries,
        )
        try:
            self._arduino.open()
            version = self._arduino.version()
            logger.info(f"Arduino 接続完了: {version}")
        except ArduinoError as e:
            logger.error(f"Arduino 接続失敗: {e}")
            logger.error("Arduino を接続してから再起動してください")
            sys.exit(1)

        # Spreadsheet 接続 (オプション)
        if cfg.google_sheets.enabled:
            try:
                self._sheets = SheetsClient(
                    credentials_file=cfg.google_sheets.credentials_file,
                    spreadsheet_id=cfg.google_sheets.spreadsheet_id,
                    sheet_settings=cfg.google_sheets.sheet_settings,
                    sheet_sensor_log=cfg.google_sheets.sheet_sensor_log,
                    sheet_watering_log=cfg.google_sheets.sheet_watering_log,
                )
                self._sheets.connect()
                logger.info("Spreadsheet 接続完了")

                # 起動時に設定を読み込み
                self._poll_sheets_settings()
            except Exception as e:
                logger.warning(f"Spreadsheet 接続失敗: {e} (ローカル設定で継続)")
                self._sheets = None

        # コントローラ初期化
        self._controller = WateringController(
            arduino=self._arduino,
            config=self._cfg,
            sheets=self._sheets,
        )

        logger.info("初期化完了。メインループを開始します。")

    def stop(self) -> None:
        """システム停止"""
        logger.info("システムを停止します...")
        self._running = False

        if self._controller:
            self._controller.emergency_stop()

        if self._arduino:
            self._arduino.close()

        logger.info("システム停止完了")

    # =========================================================================
    # メインループ
    # =========================================================================

    def run(self) -> None:
        """メインループ"""
        self._running = True

        # Ctrl+C で安全に停止
        def signal_handler(sig, frame):
            logger.info("割り込み検知 (Ctrl+C)")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while self._running:
            try:
                now = datetime.now()
                current_time = time.time()

                # --- 1. Spreadsheet ポーリング ---
                sheets_interval = self._cfg.schedule.sheets_poll_interval_min * 60
                if (
                    self._sheets
                    and current_time - self._last_sheets_poll >= sheets_interval
                ):
                    self._poll_sheets_settings()
                    self._check_manual_trigger()
                    self._last_sheets_poll = current_time

                # --- 2. 定時給水判定 ---
                self._check_scheduled_watering(now)

                # --- 3. 定期センサー記録 ---
                sensor_interval = self._cfg.schedule.sensor_interval_min * 60
                if current_time - self._last_sensor_read >= sensor_interval:
                    self._periodic_sensor_read()
                    self._last_sensor_read = current_time

                # --- 日付変更で判定済みリストをリセット ---
                if now.hour == 0 and now.minute == 0:
                    self._last_watering_checks.clear()

                # スリープ (CPU 負荷軽減)
                time.sleep(10)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"メインループエラー: {e}", exc_info=True)
                time.sleep(60)  # エラー時は少し長めに待機

    def run_once(self) -> None:
        """1回だけ給水判定を実行して終了 (テスト用)"""
        if self._controller:
            result = self._controller.check_and_water(trigger="AUTO")
            if result.executed:
                logger.info(f"結果: {result.message}")
            else:
                logger.info(f"給水なし: {result.skipped_reason}")

    # =========================================================================
    # 内部処理
    # =========================================================================

    def _check_scheduled_watering(self, now: datetime) -> None:
        """スケジュール時刻になったら給水判定を実行"""
        current_hm = now.strftime("%H:%M")

        if current_hm in self._cfg.schedule.watering_times:
            if current_hm not in self._last_watering_checks:
                logger.info(f"スケジュール時刻 {current_hm} → 給水判定開始")
                self._last_watering_checks.add(current_hm)
                self._controller.check_and_water(trigger="AUTO")

    def _poll_sheets_settings(self) -> None:
        """Spreadsheet から設定を読み取ってマージ"""
        if self._sheets is None:
            return
        try:
            sheets_data = self._sheets.read_settings()
            if sheets_data:
                self._config_manager.merge_sheets_settings(sheets_data)
                logger.debug("Spreadsheet 設定を反映しました")
        except Exception as e:
            logger.warning(f"Spreadsheet 設定読み取り失敗: {e}")

    def _check_manual_trigger(self) -> None:
        """Spreadsheet の手動給水フラグをチェック"""
        if self._sheets is None:
            return
        try:
            sheets_data = self._sheets.read_settings()
            if self._config_manager.is_manual_trigger(sheets_data):
                logger.info("手動給水指示を検出!")
                self._sheets.reset_manual_trigger()
                self._controller.check_and_water(trigger="MANUAL")
        except Exception as e:
            logger.warning(f"手動給水チェック失敗: {e}")

    def _periodic_sensor_read(self) -> None:
        """定期センサーデータ取得・記録"""
        try:
            data = self._arduino.read_all()
            logger.info(
                f"[定期] 土壌={data.soil}, 水位={'OK' if data.water_ok else 'NG'}, "
                f"温度={data.temperature}, 湿度={data.humidity}"
            )

            if self._sheets:
                self._sheets.append_sensor_log(
                    soil_values=data.soil,
                    water_ok=data.water_ok,
                    temperature=data.temperature,
                    humidity=data.humidity,
                )

            # 水位不足アラート
            if not data.water_ok:
                logger.warning("水位不足を検知!")

        except ArduinoError as e:
            logger.error(f"定期センサー読み取り失敗: {e}")


# =============================================================================
# エントリポイント
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="自動給水システム")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
        help="設定ファイルパス (default: raspi/config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回だけ給水判定を実行して終了 (テスト用)",
    )
    args = parser.parse_args()

    system = WateringSystem(config_path=args.config)
    system.start()

    if args.once:
        system.run_once()
    else:
        system.run()

    system.stop()


if __name__ == "__main__":
    main()
