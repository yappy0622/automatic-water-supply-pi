"""
serial_driver.py - Arduino シリアル通信ドライバ

Arduino に対してコマンドを送信し、レスポンスを受信するためのドライバ。
Phase 1 (MVP) で使用する中核モジュール。

使用例:
    driver = ArduinoDriver("/dev/ttyUSB0")
    driver.open()

    soil = driver.read_soil()        # → [512, 480]
    water = driver.read_water()      # → True
    driver.pump_on()                 # → ポンプ起動
    driver.pump_off()                # → ポンプ停止
    all_data = driver.read_all()     # → 全センサー一括取得

    driver.close()
"""

import serial
import time
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class SensorReadAll:
    """READ_ALL の解析結果"""
    soil: list[int]
    water_ok: bool
    temperature: Optional[float]
    humidity: Optional[float]
    light_lux: Optional[float]
    ec_value: Optional[float] = None  # EC (mS/cm) 土壌電気伝導度
    pump_running: bool = False


# =============================================================================
# 例外クラス
# =============================================================================

class ArduinoError(Exception):
    """Arduino 通信の基底例外"""
    pass


class ArduinoTimeoutError(ArduinoError):
    """Arduino からの応答タイムアウト"""
    pass


class ArduinoCommandError(ArduinoError):
    """Arduino が ERR: を返した場合"""
    pass


class ArduinoNoWaterError(ArduinoCommandError):
    """水位不足でポンプ起動が拒否された"""
    pass


# =============================================================================
# ドライバ本体
# =============================================================================

class ArduinoDriver:
    """
    Arduino シリアル通信ドライバ

    コマンドを送信し、レスポンスを解析して Python オブジェクトとして返す。
    リトライ・タイムアウト処理を内包する。
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baud_rate: int = 9600,
        timeout: float = 2.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._serial: Optional[serial.Serial] = None

    # -------------------------------------------------------------------------
    # 接続管理
    # -------------------------------------------------------------------------

    def open(self) -> None:
        """シリアルポートを開く"""
        if self._serial and self._serial.is_open:
            logger.warning("既に接続済み。再接続します。")
            self.close()

        logger.info(f"Arduino に接続: {self.port} @ {self.baud_rate} baud")
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            timeout=self.timeout,
        )

        # Arduino はシリアル接続時にリセットされるため、起動待機
        time.sleep(2.0)

        # 起動メッセージ (READY:...) を読み捨て
        self._flush_input()

        # 接続確認
        if not self.ping():
            raise ArduinoError("Arduino が応答しません")

        logger.info("Arduino 接続完了")

    def close(self) -> None:
        """シリアルポートを閉じる"""
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Arduino 切断")
        self._serial = None

    def is_connected(self) -> bool:
        """接続状態を返す"""
        return self._serial is not None and self._serial.is_open

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -------------------------------------------------------------------------
    # 低レベル送受信
    # -------------------------------------------------------------------------

    def _flush_input(self) -> None:
        """受信バッファをクリア"""
        if self._serial:
            self._serial.reset_input_buffer()

    def _send_command(self, command: str) -> str:
        """
        コマンドを送信し、1行のレスポンスを受信する。
        リトライ付き。

        Returns:
            レスポンス文字列 (改行なし)

        Raises:
            ArduinoTimeoutError: 全リトライ失敗
            ArduinoCommandError: ERR: レスポンス受信
        """
        if not self.is_connected():
            raise ArduinoError("Arduino に接続されていません")

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # バッファクリア
                self._flush_input()

                # コマンド送信
                cmd_bytes = (command.strip() + "\n").encode("ascii")
                self._serial.write(cmd_bytes)
                self._serial.flush()

                logger.debug(f"[TX] {command} (attempt {attempt}/{self.max_retries})")

                # レスポンス受信
                raw = self._serial.readline()
                if not raw:
                    raise ArduinoTimeoutError(f"応答なし: {command}")

                response = raw.decode("ascii").strip()
                logger.debug(f"[RX] {response}")

                # エラーチェック
                if response.startswith("ERR:"):
                    error_code = response[4:]
                    if error_code == "NO_WATER":
                        raise ArduinoNoWaterError("給水タンクの水が不足しています")
                    raise ArduinoCommandError(f"Arduino エラー: {error_code}")

                # WARN メッセージが混入した場合はログに記録して再読み取り
                if response.startswith("WARN:"):
                    logger.warning(f"Arduino 警告: {response}")
                    # もう1行読み取る (本来のレスポンス)
                    raw = self._serial.readline()
                    if raw:
                        response = raw.decode("ascii").strip()

                return response

            except ArduinoCommandError:
                raise  # エラーレスポンスはリトライしない
            except Exception as e:
                last_error = e
                logger.warning(f"コマンド '{command}' 失敗 (attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        raise ArduinoTimeoutError(
            f"全{self.max_retries}回のリトライ失敗: {command}"
        ) from last_error

    # -------------------------------------------------------------------------
    # 高レベルコマンド
    # -------------------------------------------------------------------------

    def ping(self) -> bool:
        """
        ヘルスチェック

        Returns:
            True: 正常応答 / False: 応答なし
        """
        try:
            response = self._send_command("PING")
            return response == "PONG"
        except ArduinoError:
            return False

    def version(self) -> str:
        """
        ファームウェアバージョン取得

        Returns:
            "WateringDriver,1.0.0" 形式の文字列
        """
        response = self._send_command("VERSION")
        # "VERSION:WateringDriver,1.0.0" → "WateringDriver,1.0.0"
        if response.startswith("VERSION:"):
            return response[8:]
        return response

    def read_soil(self) -> list[int]:
        """
        土壌湿度センサー値を読み取る

        Returns:
            各センサーの値のリスト (例: [512, 480])
        """
        response = self._send_command("READ_SOIL")
        # "SOIL:512,480" → [512, 480]
        if response.startswith("SOIL:"):
            values = response[5:].split(",")
            return [int(v) for v in values]
        raise ArduinoError(f"予期しないレスポンス: {response}")

    def read_water(self) -> bool:
        """
        水位センサーを読み取る

        Returns:
            True: 水あり / False: 水不足
        """
        response = self._send_command("READ_WATER")
        # "WATER:1" → True
        if response.startswith("WATER:"):
            return response[6:] == "1"
        raise ArduinoError(f"予期しないレスポンス: {response}")

    def read_dht(self) -> tuple[float, float]:
        """
        温度・湿度を読み取る

        Returns:
            (温度, 湿度) のタプル

        Raises:
            ArduinoCommandError: DHT読み取り失敗
        """
        response = self._send_command("READ_DHT")
        # "DHT:25.3,60.2" → (25.3, 60.2)
        if response.startswith("DHT:"):
            values = response[4:].split(",")
            return (float(values[0]), float(values[1]))
        raise ArduinoError(f"予期しないレスポンス: {response}")

    def read_light(self) -> Optional[float]:
        """
        照度センサー値を読み取る

        Returns:
            照度 (lux)  None: センサー未接続
        """
        response = self._send_command("READ_LIGHT")
        # "LIGHT:350.0"
        if response.startswith("LIGHT:"):
            try:
                return float(response[6:])
            except ValueError:
                return None
        raise ArduinoError(f"予期しないレスポンス: {response}")

    def read_ec(self) -> Optional[float]:
        """
        EC (電気伝導度) センサー値を読み取る

        Returns:
            EC 値 (mS/cm)  None: センサー未接続
        """
        response = self._send_command("READ_EC")
        # "EC:1.25"
        if response.startswith("EC:"):
            try:
                return float(response[3:])
            except ValueError:
                return None
        raise ArduinoError(f"予期しないレスポンス: {response}")

    def read_all(self) -> SensorReadAll:
        """
        全センサー一括読み取り

        Returns:
            SensorReadAll データクラス
        """
        response = self._send_command("READ_ALL")
        # "SOIL:512,480;WATER:1;DHT:25.3,60.2;LIGHT:350.0;PUMP:OFF"
        parts = {}
        for segment in response.split(";"):
            key, _, value = segment.partition(":")
            parts[key] = value

        # SOIL
        soil = [int(v) for v in parts.get("SOIL", "0").split(",")]

        # WATER
        water_ok = parts.get("WATER", "0") == "1"

        # DHT
        dht_raw = parts.get("DHT", "ERR,ERR")
        dht_vals = dht_raw.split(",")
        try:
            temperature = float(dht_vals[0])
            humidity = float(dht_vals[1])
        except (ValueError, IndexError):
            temperature = None
            humidity = None

        # LIGHT
        light_raw = parts.get("LIGHT", None)
        light_lux = None
        if light_raw is not None:
            try:
                light_lux = float(light_raw)
            except ValueError:
                light_lux = None

        # EC
        ec_raw = parts.get("EC", None)
        ec_value = None
        if ec_raw is not None:
            try:
                ec_value = float(ec_raw)
            except ValueError:
                ec_value = None

        # PUMP
        pump_running = parts.get("PUMP", "OFF") == "ON"

        return SensorReadAll(
            soil=soil,
            water_ok=water_ok,
            temperature=temperature,
            humidity=humidity,
            light_lux=light_lux,
            ec_value=ec_value,
            pump_running=pump_running,
        )

    def pump_on(self) -> bool:
        """
        ポンプをONにする

        Returns:
            True: 起動成功

        Raises:
            ArduinoNoWaterError: 水位不足で拒否
        """
        response = self._send_command("PUMP_ON")
        return response == "OK:PUMP_ON"

    def pump_off(self) -> bool:
        """
        ポンプをOFFにする

        Returns:
            True: 停止成功
        """
        response = self._send_command("PUMP_OFF")
        return response == "OK:PUMP_OFF"

    def status_pump(self) -> bool:
        """
        ポンプ状態を確認する

        Returns:
            True: 稼働中 / False: 停止中
        """
        response = self._send_command("STATUS_PUMP")
        # "PUMP:ON" or "PUMP:OFF"
        if response.startswith("PUMP:"):
            return response[5:] == "ON"
        raise ArduinoError(f"予期しないレスポンス: {response}")
