#!/usr/bin/env python3
"""
main.py - 自動給水システム エントリポイント

以下のループを実行する:
  1. 定時になったら給水判定
  2. 定期的にセンサーデータを取得して記録
  3. Spreadsheet をポーリングして設定変更・手動給水指示を反映
  4. 定期的にグラフを生成して Discord に送信

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
from raspi.data.sensor_log import SensorCSVLogger
from raspi.data.grapher import SensorGrapher
from raspi.external.discord_notify import DiscordNotifier
from raspi.external.weather import WeatherClient, WeatherForecast
from raspi.logic.plant_advisor import PlantAdvisor, PlantDiagnosis

logger = logging.getLogger(__name__)


class WateringSystem:
    """自動給水システム メインクラス"""

    def __init__(self, config_path: str):
        self._config_manager = ConfigManager(config_path)
        self._cfg = self._config_manager.config
        self._arduino: Optional[ArduinoDriver] = None
        self._sheets: Optional[SheetsClient] = None
        self._controller: Optional[WateringController] = None
        self._discord: Optional[DiscordNotifier] = None
        self._weather: Optional[WeatherClient] = None
        self._advisor: Optional[PlantAdvisor] = None
        self._running = False

        # タイミング管理
        self._last_sensor_read = 0.0
        self._last_graph_gen = 0.0
        self._last_diagnosis = 0.0
        self._last_watering_checks: set[str] = set()  # 今日チェック済みの時刻

        # ローカルCSVロガー・グラフ生成
        self._csv_logger: Optional[SensorCSVLogger] = None
        self._grapher: Optional[SensorGrapher] = None

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
        logger.info(f"センサー取得間隔 : {cfg.schedule.sensor_interval_min}分")
        logger.info(f"メインループ間隔 : {cfg.schedule.main_loop_sleep_sec}秒")

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

        # Discord 通知 (オプション)
        if cfg.notification.discord_webhook_url:
            try:
                self._discord = DiscordNotifier(
                    webhook_url=cfg.notification.discord_webhook_url,
                )
                logger.info("Discord 通知: 有効")
            except ImportError:
                logger.warning("requests がインストールされていません。Discord通知は無効です。")
                self._discord = None
        else:
            logger.info("Discord 通知: 無効 (webhook URL 未設定)")

        # コントローラ初期化
        self._controller = WateringController(
            arduino=self._arduino,
            config=self._cfg,
            sheets=self._sheets,
        )

        # ローカルCSVログ + グラフ生成
        self._csv_logger = SensorCSVLogger()
        try:
            self._grapher = SensorGrapher(
                csv_path=self._csv_logger.csv_path,
                soil_threshold=cfg.watering.soil_threshold,
            )
        except ImportError:
            logger.warning("matplotlib/pandas がインストールされていません。グラフ生成は無効です。")
            self._grapher = None

        # 天気API (Open-Meteo, 無料)
        try:
            self._weather = WeatherClient()
            logger.info("天気API: 有効 (Open-Meteo)")
        except ImportError:
            logger.warning("天気API: 無効 (requests 未インストール)")
            self._weather = None

        # モロヘイヤ栽培アドバイザー
        self._advisor = PlantAdvisor()
        logger.info("栽培アドバイザー: 有効 (モロヘイヤ)")

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

                # --- 1. 定期センサー記録 + Sheetsポーリング (同周期で省電力) ---
                sensor_interval = self._cfg.schedule.sensor_interval_min * 60
                if current_time - self._last_sensor_read >= sensor_interval:
                    self._periodic_sensor_read()
                    self._last_sensor_read = current_time

                    # Sheets ポーリングもセンサー記録と同タイミング (省電力)
                    if self._sheets:
                        self._poll_sheets_settings()
                        self._check_manual_trigger()

                # --- 2. 定時給水判定 ---
                self._check_scheduled_watering(now)

                # --- 3. 定期グラフ生成 ---
                graph_interval = self._cfg.schedule.graph_interval_hours * 3600
                if current_time - self._last_graph_gen >= graph_interval:
                    self._generate_graphs()
                    self._last_graph_gen = current_time

                # --- 4. 定期栽培診断 (12時間ごと) ---
                diagnosis_interval = 12 * 3600
                if current_time - self._last_diagnosis >= diagnosis_interval:
                    self._run_diagnosis()
                    self._last_diagnosis = current_time

                # --- 日付変更で判定済みリストをリセット ---
                if now.hour == 0 and now.minute == 0:
                    self._last_watering_checks.clear()

                # スリープ (省電力: デフォルト30秒)
                time.sleep(self._cfg.schedule.main_loop_sleep_sec)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"メインループエラー: {e}", exc_info=True)
                self._notify_error(str(e))
                time.sleep(60)  # エラー時は少し長めに待機

    def run_once(self) -> None:
        """1回だけ給水判定を実行して終了 (テスト用)"""
        if self._controller:
            result = self._controller.check_and_water(trigger="AUTO")
            if result.executed:
                logger.info(f"結果: {result.message}")
                self._notify_watering(result)
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
                # 天気予報チェック: 雨が降るなら給水スキップ
                if self._weather:
                    forecast = self._weather.get_forecast()
                    if forecast.success and forecast.should_skip_watering:
                        logger.info(
                            f"天気予報: {forecast.rain_hours}時間後に雨 "
                            f"(24h計 {forecast.rain_total_24h:.1f}mm) → 給水スキップ"
                        )
                        self._last_watering_checks.add(current_hm)
                        return

                logger.info(f"スケジュール時刻 {current_hm} → 給水判定開始")
                self._last_watering_checks.add(current_hm)
                result = self._controller.check_and_water(trigger="AUTO")
                if result.executed:
                    self._notify_watering(result)

    def _poll_sheets_settings(self) -> None:
        """Spreadsheet から設定を読み取ってマージ"""
        if self._sheets is None:
            return
        try:
            sheets_data = self._sheets.read_settings()
            if sheets_data:
                self._config_manager.merge_sheets_settings(sheets_data)
                # グラフの閾値も更新
                if self._grapher:
                    self._grapher.set_threshold(self._cfg.watering.soil_threshold)
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
                result = self._controller.check_and_water(trigger="MANUAL")
                if result.executed:
                    self._notify_watering(result)
        except Exception as e:
            logger.warning(f"手動給水チェック失敗: {e}")

    def _periodic_sensor_read(self) -> None:
        """定期センサーデータ取得・記録"""
        try:
            data = self._arduino.read_all()
            logger.info(
                f"[定期] 土壌={data.soil}, 水位={'OK' if data.water_ok else 'NG'}, "
                f"温度={data.temperature}, 湿度={data.humidity}, "
                f"照度={data.light_lux}, EC={data.ec_value}"
            )

            # ローカルCSVに記録 (Sheets が落ちてもデータは残る)
            if self._csv_logger:
                self._csv_logger.append(data)

            # Spreadsheet に記録
            if self._sheets:
                self._sheets.append_sensor_log(
                    soil_values=data.soil,
                    water_ok=data.water_ok,
                    temperature=data.temperature,
                    humidity=data.humidity,
                    light_lux=data.light_lux,
                    ec_value=data.ec_value,
                )

            # 水位不足アラート
            if not data.water_ok:
                logger.warning("水位不足を検知!")
                self._notify_low_water()

            # 照度履歴をアドバイザーに記録
            if self._advisor and data.light_lux is not None:
                self._advisor.record_light(data.light_lux)

        except ArduinoError as e:
            logger.error(f"定期センサー読み取り失敗: {e}")
            self._notify_error(f"センサー読み取り失敗: {e}")

    def _run_diagnosis(self) -> None:
        """モロヘイヤ栽培診断を実行し、Discordに結果を通知"""
        if not self._advisor:
            return
        try:
            data = self._arduino.read_all()
            diagnosis = self._advisor.diagnose_from_sensor_data(data)
            logger.info(f"栽培診断: {diagnosis.summary}")

            # 天気情報も併せて取得
            weather_fields = []
            if self._weather:
                forecast = self._weather.get_forecast()
                if forecast.success:
                    weather_fields = forecast.to_discord_fields()
                    logger.info(f"天気: {forecast.weather_summary}")

            # Discord に診断結果を送信
            if self._discord and self._discord.is_enabled:
                embed = diagnosis.to_discord_embed()
                if weather_fields:
                    embed["fields"].extend(weather_fields)
                self._discord._send(embeds=[embed])

        except ArduinoError as e:
            logger.error(f"栽培診断失敗: {e}")
        except Exception as e:
            logger.warning(f"栽培診断エラー: {e}")

    def _generate_graphs(self) -> None:
        """センサーデータのグラフを生成"""
        if self._grapher is None:
            return
        try:
            path = self._grapher.generate_all()
            if path:
                logger.info(f"グラフ生成完了: {path}")
                # Discord にグラフを送信
                if self._discord and self._discord.is_enabled:
                    self._discord.send_graph(path)
        except Exception as e:
            logger.warning(f"グラフ生成失敗: {e}")

    # =========================================================================
    # Discord 通知ヘルパー
    # =========================================================================

    def _notify_watering(self, result) -> None:
        """給水結果を Discord に通知"""
        if not self._discord or not self._discord.is_enabled:
            return
        if not self._cfg.notification.notify_on_watering:
            return
        try:
            self._discord.send_watering_report(
                trigger=result.trigger,
                soil_before=result.soil_before,
                soil_after=result.soil_after,
                pump_duration=result.pump_duration,
                success=result.success,
                message=result.message,
            )
        except Exception as e:
            logger.warning(f"Discord 給水通知失敗: {e}")

    def _notify_low_water(self) -> None:
        """水不足を Discord に通知"""
        if not self._discord or not self._discord.is_enabled:
            return
        if not self._cfg.notification.notify_on_low_water:
            return
        try:
            self._discord.send_low_water_alert()
        except Exception as e:
            logger.warning(f"Discord 水不足通知失敗: {e}")

    def _notify_error(self, error_message: str) -> None:
        """エラーを Discord に通知"""
        if not self._discord or not self._discord.is_enabled:
            return
        if not self._cfg.notification.notify_on_error:
            return
        try:
            self._discord.send_error(error_message)
        except Exception as e:
            logger.warning(f"Discord エラー通知失敗: {e}")


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
