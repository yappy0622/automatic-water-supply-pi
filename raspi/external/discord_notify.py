"""
discord_notify.py - Discord Webhook 通知

給水実行・水不足アラート・エラー通知を Discord に送信する。
グラフ画像の添付にも対応。

セットアップ:
  1. Discord サーバーの設定 → 連携サービス → ウェブフック → 新しいウェブフック
  2. ウェブフック URL をコピー
  3. config.yaml の notification.discord_webhook_url に貼り付け

使用例:
    notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/...")
    notifier.send_watering_report(result, sensor_data)
    notifier.send_low_water_alert()
    notifier.send_error("Arduino 接続失敗")
    notifier.send_graph("/path/to/graph.png")  # 画像添付
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.info("requests がインストールされていません。Discord通知は無効です。")


class DiscordNotifier:
    """Discord Webhook 通知クライアント"""

    def __init__(self, webhook_url: str, bot_name: str = "🌱 給水ボット"):
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests がインストールされていません。\n"
                "  pip install requests"
            )

        self._webhook_url = webhook_url
        self._bot_name = bot_name

        if not webhook_url:
            logger.warning("Discord Webhook URL が設定されていません。通知は送信されません。")

    @property
    def is_enabled(self) -> bool:
        return bool(self._webhook_url)

    # =========================================================================
    # 低レベル送信
    # =========================================================================

    def _send(
        self,
        content: str = "",
        embeds: Optional[list[dict]] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """
        Discord Webhook にメッセージを送信。

        Args:
            content: テキスト本文
            embeds: Embed オブジェクトのリスト
            file_path: 添付ファイルパス (画像など)

        Returns:
            True: 送信成功
        """
        if not self.is_enabled:
            return False

        try:
            payload = {"username": self._bot_name}
            if content:
                payload["content"] = content
            if embeds:
                payload["embeds"] = embeds

            if file_path:
                with open(file_path, "rb") as f:
                    files = {"file": (file_path.split("/")[-1], f)}
                    resp = requests.post(
                        self._webhook_url,
                        data={"payload_json": __import__("json").dumps(payload)},
                        files=files,
                        timeout=15,
                    )
            else:
                resp = requests.post(
                    self._webhook_url,
                    json=payload,
                    timeout=15,
                )

            if resp.status_code in (200, 204):
                logger.debug("Discord 通知送信成功")
                return True
            else:
                logger.warning(
                    f"Discord 通知失敗: HTTP {resp.status_code} - {resp.text[:200]}"
                )
                return False

        except Exception as e:
            logger.error(f"Discord 通知送信エラー: {e}")
            return False

    # =========================================================================
    # 通知メソッド
    # =========================================================================

    def send_watering_report(
        self,
        trigger: str,
        soil_before: list[int],
        soil_after: list[int],
        pump_duration: int,
        success: bool,
        message: str = "",
    ) -> bool:
        """給水実行レポートを送信"""
        avg_before = sum(soil_before) / len(soil_before) if soil_before else 0
        avg_after = sum(soil_after) / len(soil_after) if soil_after else 0

        color = 0x00FF00 if success else 0xFF6600  # 緑 or オレンジ
        status_emoji = "✅" if success else "⚠️"

        embed = {
            "title": f"{status_emoji} 給水レポート",
            "color": color,
            "fields": [
                {"name": "トリガー", "value": trigger, "inline": True},
                {"name": "結果", "value": "成功" if success else "失敗", "inline": True},
                {"name": "給水時間", "value": f"{pump_duration}秒", "inline": True},
                {
                    "name": "土壌湿度 (給水前)",
                    "value": f"{avg_before:.0f} ({soil_before})",
                    "inline": True,
                },
                {
                    "name": "土壌湿度 (給水後)",
                    "value": f"{avg_after:.0f} ({soil_after})" if soil_after else "未計測",
                    "inline": True,
                },
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

        if message:
            embed["description"] = message

        return self._send(embeds=[embed])

    def send_low_water_alert(self) -> bool:
        """水不足アラートを送信"""
        embed = {
            "title": "🚨 水不足アラート",
            "description": "給水タンクの水が不足しています。\n補充してください。",
            "color": 0xFF0000,
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._send(embeds=[embed])

    def send_error(self, error_message: str) -> bool:
        """エラー通知を送信"""
        embed = {
            "title": "❌ エラー",
            "description": f"```\n{error_message}\n```",
            "color": 0xFF0000,
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._send(embeds=[embed])

    def send_sensor_summary(
        self,
        soil_values: list[int],
        water_ok: bool,
        temperature: Optional[float],
        humidity: Optional[float],
        light_lux: Optional[float] = None,
        ec_value: Optional[float] = None,
    ) -> bool:
        """センサーデータ日次サマリーを送信"""
        avg_soil = sum(soil_values) / len(soil_values) if soil_values else 0

        fields = [
            {"name": "🌱 土壌湿度", "value": f"平均 {avg_soil:.0f} ({soil_values})", "inline": False},
            {"name": "💧 水位", "value": "正常" if water_ok else "⚠️ 不足", "inline": True},
        ]
        if temperature is not None:
            fields.append({"name": "🌡️ 温度", "value": f"{temperature:.1f} °C", "inline": True})
        if humidity is not None:
            fields.append({"name": "💨 湿度", "value": f"{humidity:.1f} %", "inline": True})
        if light_lux is not None:
            fields.append({"name": "☀️ 照度", "value": f"{light_lux:.0f} lux", "inline": True})
        if ec_value is not None:
            fields.append({"name": "⚡ EC (土壌伝導度)", "value": f"{ec_value:.2f} mS/cm", "inline": True})

        embed = {
            "title": "📊 センサーデータ",
            "color": 0x3498DB,
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._send(embeds=[embed])

    def send_graph(self, image_path: str, title: str = "📈 センサー推移グラフ") -> bool:
        """グラフ画像を送信"""
        embed = {
            "title": title,
            "color": 0x3498DB,
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._send(embeds=[embed], file_path=image_path)

    def send_daily_report(
        self,
        watering_count: int,
        total_pump_seconds: int,
        avg_soil: float,
        min_soil: float,
        max_soil: float,
        water_ok: bool,
        graph_path: Optional[str] = None,
    ) -> bool:
        """日次レポートを送信"""
        embed = {
            "title": "📋 日次レポート",
            "color": 0x2ECC71,
            "fields": [
                {"name": "給水回数", "value": f"{watering_count} 回", "inline": True},
                {"name": "合計給水時間", "value": f"{total_pump_seconds} 秒", "inline": True},
                {"name": "💧 水位", "value": "正常" if water_ok else "⚠️ 不足", "inline": True},
                {"name": "🌱 土壌湿度 (平均)", "value": f"{avg_soil:.0f}", "inline": True},
                {"name": "🌱 土壌湿度 (最小)", "value": f"{min_soil:.0f}", "inline": True},
                {"name": "🌱 土壌湿度 (最大)", "value": f"{max_soil:.0f}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._send(embeds=[embed], file_path=graph_path)
