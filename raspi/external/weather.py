"""
weather.py - 天気API連携

Open-Meteo (無料・APIキー不要) を使って天気予報を取得し、
給水判断や栽培アドバイスに活用する。

機能:
  1. 現在の天気取得 (気温, 降水量, 日照, 風速)
  2. 今後24時間の降水予報 → 雨の場合は給水をスキップ
  3. 日照予報 → 植物の日当たり予測

Open-Meteo API:
  - 無料, APIキー不要
  - 制限: 10,000 リクエスト/日 (十分すぎる)
  - ドキュメント: https://open-meteo.com/

使用例:
    weather = WeatherClient(latitude=35.6762, longitude=139.6503)  # 東京
    forecast = weather.get_forecast()
    if forecast.rain_expected:
        print(f"今後 {forecast.rain_hours}時間以内に雨予報 → 給水スキップ推奨")
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.info("requests がインストールされていません。天気API連携は無効です。")


# Open-Meteo API エンドポイント
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class WeatherForecast:
    """天気予報データ"""
    timestamp: str

    # 現在の天気
    current_temp: Optional[float] = None       # 気温 (°C)
    current_humidity: Optional[float] = None   # 相対湿度 (%)
    current_rain: Optional[float] = None       # 降水量 (mm)
    current_cloud: Optional[int] = None        # 雲量 (%)
    current_wind: Optional[float] = None       # 風速 (km/h)
    current_uv: Optional[float] = None         # UV インデックス

    # 予報 (今後24時間)
    rain_expected: bool = False                 # 雨予報あり
    rain_hours: Optional[int] = None           # 何時間後に雨
    rain_total_24h: float = 0.0                # 24時間累計降水量 (mm)
    max_temp_24h: Optional[float] = None       # 24時間最高気温
    min_temp_24h: Optional[float] = None       # 24時間最低気温
    sunshine_hours: Optional[float] = None     # 日照時間予報 (時間)

    # ステータス
    success: bool = False
    error_message: str = ""

    @property
    def should_skip_watering(self) -> bool:
        """雨予報があり給水スキップを推奨するか"""
        # 今後6時間以内に雨で、累計2mm以上ならスキップ推奨
        if self.rain_expected and self.rain_hours is not None:
            if self.rain_hours <= 6 and self.rain_total_24h >= 2.0:
                return True
        return False

    @property
    def weather_summary(self) -> str:
        """天気の要約文字列"""
        if not self.success:
            return f"天気情報取得失敗: {self.error_message}"

        parts = []
        if self.current_temp is not None:
            parts.append(f"気温 {self.current_temp:.1f}°C")
        if self.current_humidity is not None:
            parts.append(f"湿度 {self.current_humidity:.0f}%")
        if self.current_rain is not None and self.current_rain > 0:
            parts.append(f"降水 {self.current_rain:.1f}mm")
        if self.current_cloud is not None:
            parts.append(f"雲量 {self.current_cloud}%")

        summary = ", ".join(parts) if parts else "データなし"

        if self.rain_expected:
            summary += f" | 🌧 {self.rain_hours}時間後に雨予報 (24h計 {self.rain_total_24h:.1f}mm)"
        else:
            summary += " | ☀ 24時間以内の雨予報なし"

        return summary

    def to_discord_fields(self) -> list[dict]:
        """Discord Embed の fields リストに変換"""
        fields = []

        if self.current_temp is not None:
            fields.append({
                "name": "🌡 気温",
                "value": f"{self.current_temp:.1f}°C",
                "inline": True,
            })
        if self.current_humidity is not None:
            fields.append({
                "name": "💧 湿度",
                "value": f"{self.current_humidity:.0f}%",
                "inline": True,
            })
        if self.current_cloud is not None:
            cloud_emoji = "☀" if self.current_cloud < 30 else "⛅" if self.current_cloud < 70 else "☁"
            fields.append({
                "name": f"{cloud_emoji} 雲量",
                "value": f"{self.current_cloud}%",
                "inline": True,
            })

        # 雨予報
        if self.rain_expected:
            fields.append({
                "name": "🌧 雨予報",
                "value": f"{self.rain_hours}時間後 (24h計 {self.rain_total_24h:.1f}mm)",
                "inline": True,
            })
        else:
            fields.append({
                "name": "☀ 雨予報",
                "value": "24時間以内の雨なし",
                "inline": True,
            })

        if self.max_temp_24h is not None and self.min_temp_24h is not None:
            fields.append({
                "name": "🌡 24h気温範囲",
                "value": f"{self.min_temp_24h:.0f}〜{self.max_temp_24h:.0f}°C",
                "inline": True,
            })

        if self.sunshine_hours is not None:
            fields.append({
                "name": "☀ 日照時間予報",
                "value": f"{self.sunshine_hours:.1f} 時間",
                "inline": True,
            })

        return fields


class WeatherClient:
    """天気API クライアント (Open-Meteo)"""

    def __init__(
        self,
        latitude: float = 35.6762,   # デフォルト: 東京
        longitude: float = 139.6503,
        timezone: str = "Asia/Tokyo",
    ):
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests がインストールされていません。\n"
                "  pip install requests"
            )

        self._latitude = latitude
        self._longitude = longitude
        self._timezone = timezone
        self._last_forecast: Optional[WeatherForecast] = None
        self._last_fetch_time: float = 0

    @property
    def last_forecast(self) -> Optional[WeatherForecast]:
        return self._last_forecast

    def get_forecast(self, cache_minutes: int = 30) -> WeatherForecast:
        """
        天気予報を取得する。

        Args:
            cache_minutes: キャッシュ時間 (分)。前回取得からこの時間以内なら再利用。

        Returns:
            WeatherForecast
        """
        import time
        now = time.time()

        # キャッシュチェック
        if (
            self._last_forecast is not None
            and self._last_forecast.success
            and (now - self._last_fetch_time) < cache_minutes * 60
        ):
            logger.debug("天気予報: キャッシュを使用")
            return self._last_forecast

        forecast = WeatherForecast(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        try:
            params = {
                "latitude": self._latitude,
                "longitude": self._longitude,
                "timezone": self._timezone,
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "rain",
                    "cloud_cover",
                    "wind_speed_10m",
                    "uv_index",
                ],
                "hourly": [
                    "temperature_2m",
                    "rain",
                    "sunshine_duration",
                ],
                "forecast_days": 1,
            }

            logger.debug(f"天気API リクエスト: lat={self._latitude}, lon={self._longitude}")
            resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # --- 現在の天気 ---
            current = data.get("current", {})
            forecast.current_temp = current.get("temperature_2m")
            forecast.current_humidity = current.get("relative_humidity_2m")
            forecast.current_rain = current.get("rain")
            forecast.current_cloud = current.get("cloud_cover")
            forecast.current_wind = current.get("wind_speed_10m")
            forecast.current_uv = current.get("uv_index")

            # --- 時間別予報 ---
            hourly = data.get("hourly", {})
            hourly_rain = hourly.get("rain", [])
            hourly_temp = hourly.get("temperature_2m", [])
            hourly_sunshine = hourly.get("sunshine_duration", [])

            # 今後24時間の降水
            if hourly_rain:
                forecast.rain_total_24h = sum(
                    r for r in hourly_rain[:24] if r is not None
                )
                # 最初に雨が降る時間を検索
                for i, rain in enumerate(hourly_rain[:24]):
                    if rain is not None and rain > 0.1:  # 0.1mm以上
                        forecast.rain_expected = True
                        forecast.rain_hours = i
                        break

            # 気温レンジ
            if hourly_temp:
                valid_temps = [t for t in hourly_temp[:24] if t is not None]
                if valid_temps:
                    forecast.max_temp_24h = max(valid_temps)
                    forecast.min_temp_24h = min(valid_temps)

            # 日照時間 (sunshine_duration は秒で返される)
            if hourly_sunshine:
                total_sunshine_sec = sum(
                    s for s in hourly_sunshine[:24] if s is not None
                )
                forecast.sunshine_hours = total_sunshine_sec / 3600.0

            forecast.success = True
            self._last_forecast = forecast
            self._last_fetch_time = now

            logger.info(f"天気取得成功: {forecast.weather_summary}")

        except requests.exceptions.RequestException as e:
            forecast.error_message = str(e)
            logger.warning(f"天気API リクエスト失敗: {e}")
        except (KeyError, ValueError, TypeError) as e:
            forecast.error_message = f"レスポンス解析エラー: {e}"
            logger.warning(f"天気API レスポンス解析失敗: {e}")
        except Exception as e:
            forecast.error_message = str(e)
            logger.error(f"天気API 予期しないエラー: {e}")

        return forecast
