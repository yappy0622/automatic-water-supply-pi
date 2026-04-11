"""
plant_advisor.py - モロヘイヤ栽培アドバイザー

センサーデータから植物の健康状態を総合診断し、
肥料の追加時期・日当たり不足・環境改善のアドバイスを出力する。

モロヘイヤ (Corchorus olitorius) の最適条件:
  - 気温: 20〜40℃ (耐暑性高い。15℃以下で生育停滞)
  - 日照: 直射日光必須 (6時間以上/日)。日陰では育たない
  - 土壌 pH: 6.0〜6.5 (弱酸性)
  - 土壌 EC: 0.5〜2.0 mS/cm (中程度の肥料濃度)
  - 土壌湿度: 適度に湿潤 (過湿は根腐れの原因)
  - 追肥: 植え付け20日後に初回、以降15〜20日ごと

使用例:
    advisor = PlantAdvisor()
    diagnosis = advisor.diagnose(
        soil_moisture=450, temperature=28.5, humidity=65.0,
        light_lux=35000.0, ec_value=1.2
    )
    print(diagnosis.summary)
    for item in diagnosis.items:
        print(f"  [{item.level}] {item.category}: {item.message}")
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# モロヘイヤの栽培パラメータ
# =============================================================================

class MoroheiyaParams:
    """モロヘイヤの最適栽培パラメータ定数"""

    # --- 気温 (°C) ---
    TEMP_MIN_GROWTH = 15.0      # これ以下で生育停滞
    TEMP_OPTIMAL_LOW = 20.0     # 最適温度下限
    TEMP_OPTIMAL_HIGH = 35.0    # 最適温度上限
    TEMP_MAX_GROWTH = 40.0      # これ以上は高温障害リスク
    TEMP_GERMINATION_MIN = 24.0 # 発芽適温下限
    TEMP_GERMINATION_MAX = 29.0 # 発芽適温上限

    # --- 日照 (lux) ---
    # 直射日光: 32,000〜100,000 lux
    # 明るい日陰: 10,000〜25,000 lux
    # 曇天: 1,000〜10,000 lux
    LIGHT_FULL_SUN = 25000.0    # 日向の最低値
    LIGHT_MIN_GROWTH = 10000.0  # 最低限必要な照度
    LIGHT_IDEAL = 40000.0       # 理想的な照度

    # --- 土壌 EC (mS/cm) ---
    # EC は土壌の塩分濃度 ≈ 肥料濃度の指標
    EC_LOW = 0.3               # 肥料不足の可能性
    EC_OPTIMAL_LOW = 0.5       # 最適下限
    EC_OPTIMAL_HIGH = 2.0      # 最適上限
    EC_HIGH = 3.0              # 肥料過多のリスク
    EC_DANGER = 4.0            # 塩害リスク

    # --- 土壌湿度 (0=乾燥, 1023=湿潤) ---
    SOIL_DRY = 300             # 乾燥 (要水やり)
    SOIL_OPTIMAL_LOW = 400     # 最適下限
    SOIL_OPTIMAL_HIGH = 700    # 最適上限
    SOIL_WET = 800             # 過湿 (根腐れリスク)

    # --- 湿度 (%) ---
    HUMIDITY_LOW = 40.0        # 乾燥しすぎ
    HUMIDITY_OPTIMAL_LOW = 50.0
    HUMIDITY_OPTIMAL_HIGH = 75.0
    HUMIDITY_HIGH = 85.0       # 病害リスク

    # --- 追肥タイミング (日) ---
    FIRST_FERTILIZE_DAYS = 20   # 植え付けから初回追肥
    FERTILIZE_INTERVAL_DAYS = 17 # 以降の追肥間隔 (15-20日)


# =============================================================================
# 診断結果データクラス
# =============================================================================

class DiagnosisLevel(str, Enum):
    """診断レベル"""
    GOOD = "GOOD"          # 良好
    INFO = "INFO"          # 参考情報
    WARNING = "WARNING"    # 注意
    ALERT = "ALERT"        # 要対応


class DiagnosisCategory(str, Enum):
    """診断カテゴリ"""
    TEMPERATURE = "temperature"
    LIGHT = "light"
    SOIL_MOISTURE = "soil_moisture"
    EC_FERTILIZER = "ec_fertilizer"
    HUMIDITY = "humidity"
    OVERALL = "overall"


@dataclass
class DiagnosisItem:
    """個別の診断項目"""
    level: DiagnosisLevel
    category: DiagnosisCategory
    title: str
    message: str
    value: Optional[float] = None
    optimal_range: str = ""


@dataclass
class PlantDiagnosis:
    """植物の総合診断結果"""
    timestamp: str
    plant_name: str = "モロヘイヤ"
    items: list[DiagnosisItem] = field(default_factory=list)
    score: int = 100  # 健康スコア (0-100)

    @property
    def summary(self) -> str:
        """診断サマリー文字列"""
        alerts = [i for i in self.items if i.level == DiagnosisLevel.ALERT]
        warnings = [i for i in self.items if i.level == DiagnosisLevel.WARNING]

        if alerts:
            return f"[要対応] {len(alerts)}件の問題あり。スコア: {self.score}/100"
        elif warnings:
            return f"[注意] {len(warnings)}件の改善点あり。スコア: {self.score}/100"
        else:
            return f"[良好] 環境は概ね良好です。スコア: {self.score}/100"

    @property
    def has_alerts(self) -> bool:
        return any(i.level == DiagnosisLevel.ALERT for i in self.items)

    @property
    def has_warnings(self) -> bool:
        return any(i.level == DiagnosisLevel.WARNING for i in self.items)

    def to_discord_embed(self) -> dict:
        """Discord Embed 形式に変換"""
        # スコアに応じた色
        if self.score >= 80:
            color = 0x4CAF50  # 緑
        elif self.score >= 60:
            color = 0xFFC107  # 黄
        elif self.score >= 40:
            color = 0xFF9800  # オレンジ
        else:
            color = 0xF44336  # 赤

        level_emoji = {
            DiagnosisLevel.GOOD: "✅",
            DiagnosisLevel.INFO: "ℹ️",
            DiagnosisLevel.WARNING: "⚠️",
            DiagnosisLevel.ALERT: "🚨",
        }

        fields = []
        for item in self.items:
            emoji = level_emoji.get(item.level, "")
            value_str = item.message
            if item.optimal_range:
                value_str += f"\n(最適: {item.optimal_range})"
            fields.append({
                "name": f"{emoji} {item.title}",
                "value": value_str,
                "inline": True,
            })

        embed = {
            "title": f"🌿 {self.plant_name} 栽培診断 (スコア: {self.score}/100)",
            "description": self.summary,
            "color": color,
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "PlantAdvisor - モロヘイヤ栽培最適化"},
        }
        return embed


# =============================================================================
# 栽培アドバイザー本体
# =============================================================================

class PlantAdvisor:
    """
    モロヘイヤ栽培アドバイザー

    各種センサーデータを受け取り、最適な栽培条件と比較して
    診断結果とアドバイスを返す。
    """

    def __init__(
        self,
        plant_date: Optional[datetime] = None,
        last_fertilize_date: Optional[datetime] = None,
    ):
        """
        Args:
            plant_date: 植え付け日 (追肥タイミング計算に使用)
            last_fertilize_date: 最後に追肥した日
        """
        self._params = MoroheiyaParams()
        self._plant_date = plant_date
        self._last_fertilize_date = last_fertilize_date

        # 日照積算用 (直近24時間のlux記録)
        self._light_history: list[tuple[datetime, float]] = []

    def update_plant_date(self, plant_date: datetime) -> None:
        """植え付け日を設定"""
        self._plant_date = plant_date

    def update_last_fertilize(self, date: datetime) -> None:
        """最終追肥日を更新"""
        self._last_fertilize_date = date

    def record_light(self, lux: float) -> None:
        """照度を記録 (日照積算計算用)"""
        now = datetime.now()
        self._light_history.append((now, lux))
        # 48時間分のデータのみ保持
        cutoff = now - timedelta(hours=48)
        self._light_history = [(t, l) for t, l in self._light_history if t >= cutoff]

    def get_daily_light_hours(self) -> Optional[float]:
        """直近24時間で照度が十分だった時間数を推定"""
        if len(self._light_history) < 2:
            return None

        now = datetime.now()
        cutoff = now - timedelta(hours=24)
        recent = [(t, l) for t, l in self._light_history if t >= cutoff]

        if len(recent) < 2:
            return None

        # 十分な日照 (> 10,000 lux) のデータポイント割合から推定
        total = len(recent)
        sunny = sum(1 for _, l in recent if l >= self._params.LIGHT_MIN_GROWTH)
        # データポイント間の間隔を考慮して時間に変換
        time_span = (recent[-1][0] - recent[0][0]).total_seconds() / 3600
        if time_span <= 0:
            return None

        return (sunny / total) * time_span

    # =========================================================================
    # 個別診断
    # =========================================================================

    def _diagnose_temperature(self, temp: float) -> DiagnosisItem:
        """気温の診断"""
        p = self._params

        if temp < p.TEMP_MIN_GROWTH:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.TEMPERATURE,
                title="気温",
                message=f"{temp:.1f}°C - 生育停滞域。室内移動や保温を検討してください。",
                value=temp,
                optimal_range=f"{p.TEMP_OPTIMAL_LOW:.0f}〜{p.TEMP_OPTIMAL_HIGH:.0f}°C",
            )
        elif temp < p.TEMP_OPTIMAL_LOW:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.TEMPERATURE,
                title="気温",
                message=f"{temp:.1f}°C - やや低め。モロヘイヤは暑さに強い植物です。",
                value=temp,
                optimal_range=f"{p.TEMP_OPTIMAL_LOW:.0f}〜{p.TEMP_OPTIMAL_HIGH:.0f}°C",
            )
        elif temp <= p.TEMP_OPTIMAL_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.GOOD,
                category=DiagnosisCategory.TEMPERATURE,
                title="気温",
                message=f"{temp:.1f}°C - 最適範囲です。",
                value=temp,
                optimal_range=f"{p.TEMP_OPTIMAL_LOW:.0f}〜{p.TEMP_OPTIMAL_HIGH:.0f}°C",
            )
        elif temp <= p.TEMP_MAX_GROWTH:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.TEMPERATURE,
                title="気温",
                message=f"{temp:.1f}°C - 高めですが、モロヘイヤは耐暑性があるので問題なし。水切れに注意。",
                value=temp,
                optimal_range=f"{p.TEMP_OPTIMAL_LOW:.0f}〜{p.TEMP_OPTIMAL_HIGH:.0f}°C",
            )
        else:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.TEMPERATURE,
                title="気温",
                message=f"{temp:.1f}°C - 高温障害リスク。日除けと頻繁な水やりを。",
                value=temp,
                optimal_range=f"{p.TEMP_OPTIMAL_LOW:.0f}〜{p.TEMP_OPTIMAL_HIGH:.0f}°C",
            )

    def _diagnose_light(self, lux: float) -> DiagnosisItem:
        """照度の診断"""
        p = self._params

        # 現在値の評価
        if lux >= p.LIGHT_FULL_SUN:
            return DiagnosisItem(
                level=DiagnosisLevel.GOOD,
                category=DiagnosisCategory.LIGHT,
                title="日照",
                message=f"{lux:.0f} lux - 十分な日照です。モロヘイヤは日光大好き。",
                value=lux,
                optimal_range=f"{p.LIGHT_FULL_SUN:.0f} lux 以上",
            )
        elif lux >= p.LIGHT_MIN_GROWTH:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.LIGHT,
                title="日照",
                message=f"{lux:.0f} lux - やや不足。モロヘイヤは直射日光が必要。日当たりの良い場所に移動を。",
                value=lux,
                optimal_range=f"{p.LIGHT_FULL_SUN:.0f} lux 以上",
            )
        else:
            # 夜間や非常に暗い場合はINFOレベル (夜は仕方ない)
            hour = datetime.now().hour
            if hour < 6 or hour > 20:
                return DiagnosisItem(
                    level=DiagnosisLevel.INFO,
                    category=DiagnosisCategory.LIGHT,
                    title="日照",
                    message=f"{lux:.0f} lux - 夜間のため測定値は参考値。",
                    value=lux,
                    optimal_range=f"{p.LIGHT_FULL_SUN:.0f} lux 以上 (日中)",
                )
            else:
                return DiagnosisItem(
                    level=DiagnosisLevel.ALERT,
                    category=DiagnosisCategory.LIGHT,
                    title="日照",
                    message=(
                        f"{lux:.0f} lux - 日照不足! モロヘイヤは日陰では育ちません。"
                        f"直射日光の当たる場所 (ベランダ等) に移動してください。"
                    ),
                    value=lux,
                    optimal_range=f"{p.LIGHT_FULL_SUN:.0f} lux 以上",
                )

    def _diagnose_ec(self, ec: float) -> DiagnosisItem:
        """EC (土壌電気伝導度 = 肥料濃度) の診断"""
        p = self._params

        if ec < p.EC_LOW:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.EC_FERTILIZER,
                title="EC (肥料濃度)",
                message=(
                    f"{ec:.2f} mS/cm - 肥料不足の可能性大。\n"
                    f"化成肥料 (N-P-K: 8-8-8) または液肥を追肥してください。\n"
                    f"モロヘイヤは窒素肥料を好み、葉の成長に重要です。"
                ),
                value=ec,
                optimal_range=f"{p.EC_OPTIMAL_LOW:.1f}〜{p.EC_OPTIMAL_HIGH:.1f} mS/cm",
            )
        elif ec < p.EC_OPTIMAL_LOW:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.EC_FERTILIZER,
                title="EC (肥料濃度)",
                message=(
                    f"{ec:.2f} mS/cm - やや肥料が薄い。\n"
                    f"追肥を検討してください。葉が小さい・色が薄い場合は窒素不足のサイン。"
                ),
                value=ec,
                optimal_range=f"{p.EC_OPTIMAL_LOW:.1f}〜{p.EC_OPTIMAL_HIGH:.1f} mS/cm",
            )
        elif ec <= p.EC_OPTIMAL_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.GOOD,
                category=DiagnosisCategory.EC_FERTILIZER,
                title="EC (肥料濃度)",
                message=f"{ec:.2f} mS/cm - 最適範囲。現在の施肥量を維持してください。",
                value=ec,
                optimal_range=f"{p.EC_OPTIMAL_LOW:.1f}〜{p.EC_OPTIMAL_HIGH:.1f} mS/cm",
            )
        elif ec <= p.EC_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.EC_FERTILIZER,
                title="EC (肥料濃度)",
                message=(
                    f"{ec:.2f} mS/cm - やや肥料過多。\n"
                    f"追肥を控え、水やりで薄めてください。"
                ),
                value=ec,
                optimal_range=f"{p.EC_OPTIMAL_LOW:.1f}〜{p.EC_OPTIMAL_HIGH:.1f} mS/cm",
            )
        else:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.EC_FERTILIZER,
                title="EC (肥料濃度)",
                message=(
                    f"{ec:.2f} mS/cm - 塩害リスク! 肥料が濃すぎます。\n"
                    f"たっぷりの水で土壌を洗い流してください (リーチング)。\n"
                    f"葉の先端が枯れている場合は塩害の兆候です。"
                ),
                value=ec,
                optimal_range=f"{p.EC_OPTIMAL_LOW:.1f}〜{p.EC_OPTIMAL_HIGH:.1f} mS/cm",
            )

    def _diagnose_soil_moisture(self, moisture: float) -> DiagnosisItem:
        """土壌湿度の診断"""
        p = self._params

        if moisture < p.SOIL_DRY:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.SOIL_MOISTURE,
                title="土壌湿度",
                message=f"{moisture:.0f} - 乾燥! 速やかに水やりしてください。",
                value=moisture,
                optimal_range=f"{p.SOIL_OPTIMAL_LOW}〜{p.SOIL_OPTIMAL_HIGH}",
            )
        elif moisture < p.SOIL_OPTIMAL_LOW:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.SOIL_MOISTURE,
                title="土壌湿度",
                message=f"{moisture:.0f} - やや乾燥。水やりを検討してください。",
                value=moisture,
                optimal_range=f"{p.SOIL_OPTIMAL_LOW}〜{p.SOIL_OPTIMAL_HIGH}",
            )
        elif moisture <= p.SOIL_OPTIMAL_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.GOOD,
                category=DiagnosisCategory.SOIL_MOISTURE,
                title="土壌湿度",
                message=f"{moisture:.0f} - 適切な湿度です。",
                value=moisture,
                optimal_range=f"{p.SOIL_OPTIMAL_LOW}〜{p.SOIL_OPTIMAL_HIGH}",
            )
        elif moisture <= p.SOIL_WET:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.SOIL_MOISTURE,
                title="土壌湿度",
                message=f"{moisture:.0f} - やや過湿。水はけを確認してください。",
                value=moisture,
                optimal_range=f"{p.SOIL_OPTIMAL_LOW}〜{p.SOIL_OPTIMAL_HIGH}",
            )
        else:
            return DiagnosisItem(
                level=DiagnosisLevel.ALERT,
                category=DiagnosisCategory.SOIL_MOISTURE,
                title="土壌湿度",
                message=(
                    f"{moisture:.0f} - 過湿! 根腐れのリスクがあります。\n"
                    f"水やりを控え、排水性の確認を。"
                ),
                value=moisture,
                optimal_range=f"{p.SOIL_OPTIMAL_LOW}〜{p.SOIL_OPTIMAL_HIGH}",
            )

    def _diagnose_humidity(self, humidity: float) -> DiagnosisItem:
        """空気湿度の診断"""
        p = self._params

        if humidity < p.HUMIDITY_LOW:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.HUMIDITY,
                title="空気湿度",
                message=f"{humidity:.1f}% - 乾燥気味。葉水（霧吹き）をすると良いです。",
                value=humidity,
                optimal_range=f"{p.HUMIDITY_OPTIMAL_LOW:.0f}〜{p.HUMIDITY_OPTIMAL_HIGH:.0f}%",
            )
        elif humidity <= p.HUMIDITY_OPTIMAL_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.GOOD,
                category=DiagnosisCategory.HUMIDITY,
                title="空気湿度",
                message=f"{humidity:.1f}% - 良好。",
                value=humidity,
                optimal_range=f"{p.HUMIDITY_OPTIMAL_LOW:.0f}〜{p.HUMIDITY_OPTIMAL_HIGH:.0f}%",
            )
        elif humidity <= p.HUMIDITY_HIGH:
            return DiagnosisItem(
                level=DiagnosisLevel.INFO,
                category=DiagnosisCategory.HUMIDITY,
                title="空気湿度",
                message=f"{humidity:.1f}% - やや高め。通風を確保してください。",
                value=humidity,
                optimal_range=f"{p.HUMIDITY_OPTIMAL_LOW:.0f}〜{p.HUMIDITY_OPTIMAL_HIGH:.0f}%",
            )
        else:
            return DiagnosisItem(
                level=DiagnosisLevel.WARNING,
                category=DiagnosisCategory.HUMIDITY,
                title="空気湿度",
                message=f"{humidity:.1f}% - 高湿度。病害 (うどんこ病等) のリスク。通風を改善してください。",
                value=humidity,
                optimal_range=f"{p.HUMIDITY_OPTIMAL_LOW:.0f}〜{p.HUMIDITY_OPTIMAL_HIGH:.0f}%",
            )

    def _check_fertilize_timing(self) -> Optional[DiagnosisItem]:
        """追肥タイミングのチェック"""
        now = datetime.now()

        if self._plant_date:
            days_since_plant = (now - self._plant_date).days

            if days_since_plant < 0:
                return None

            # 植え付け直後
            if days_since_plant < self._params.FIRST_FERTILIZE_DAYS:
                days_until = self._params.FIRST_FERTILIZE_DAYS - days_since_plant
                return DiagnosisItem(
                    level=DiagnosisLevel.INFO,
                    category=DiagnosisCategory.EC_FERTILIZER,
                    title="追肥スケジュール",
                    message=f"植え付け{days_since_plant}日目。初回追肥まであと{days_until}日。",
                )

        if self._last_fertilize_date:
            days_since_fert = (now - self._last_fertilize_date).days
            if days_since_fert >= self._params.FERTILIZE_INTERVAL_DAYS:
                overdue = days_since_fert - self._params.FERTILIZE_INTERVAL_DAYS
                return DiagnosisItem(
                    level=DiagnosisLevel.WARNING if overdue < 5 else DiagnosisLevel.ALERT,
                    category=DiagnosisCategory.EC_FERTILIZER,
                    title="追肥スケジュール",
                    message=(
                        f"前回追肥から{days_since_fert}日経過。追肥時期です。\n"
                        f"化成肥料 (8-8-8) を少量、株元に施してください。"
                    ),
                )
            else:
                days_until = self._params.FERTILIZE_INTERVAL_DAYS - days_since_fert
                return DiagnosisItem(
                    level=DiagnosisLevel.GOOD,
                    category=DiagnosisCategory.EC_FERTILIZER,
                    title="追肥スケジュール",
                    message=f"前回追肥から{days_since_fert}日目。次回追肥まで約{days_until}日。",
                )

        return None

    # =========================================================================
    # 総合診断
    # =========================================================================

    def diagnose(
        self,
        soil_moisture: Optional[float] = None,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        light_lux: Optional[float] = None,
        ec_value: Optional[float] = None,
    ) -> PlantDiagnosis:
        """
        センサーデータからモロヘイヤの栽培状態を総合診断する。

        Args:
            soil_moisture: 土壌湿度 (0-1023, 2センサーの平均)
            temperature: 気温 (°C)
            humidity: 空気湿度 (%)
            light_lux: 照度 (lux)
            ec_value: 土壌EC (mS/cm)

        Returns:
            PlantDiagnosis 総合診断結果
        """
        diagnosis = PlantDiagnosis(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        score = 100
        penalty_weight = {
            DiagnosisLevel.ALERT: 20,
            DiagnosisLevel.WARNING: 8,
            DiagnosisLevel.INFO: 0,
            DiagnosisLevel.GOOD: 0,
        }

        # --- 各センサー診断 ---
        if temperature is not None:
            item = self._diagnose_temperature(temperature)
            diagnosis.items.append(item)
            score -= penalty_weight[item.level]

        if light_lux is not None:
            item = self._diagnose_light(light_lux)
            diagnosis.items.append(item)
            score -= penalty_weight[item.level]
            # 照度履歴に記録
            self.record_light(light_lux)

        if ec_value is not None:
            item = self._diagnose_ec(ec_value)
            diagnosis.items.append(item)
            score -= penalty_weight[item.level]

        if soil_moisture is not None:
            item = self._diagnose_soil_moisture(soil_moisture)
            diagnosis.items.append(item)
            score -= penalty_weight[item.level]

        if humidity is not None:
            item = self._diagnose_humidity(humidity)
            diagnosis.items.append(item)
            score -= penalty_weight[item.level]

        # --- 追肥タイミング ---
        fert_item = self._check_fertilize_timing()
        if fert_item:
            diagnosis.items.append(fert_item)
            score -= penalty_weight[fert_item.level]

        # --- 日照積算 (データがあれば) ---
        daily_hours = self.get_daily_light_hours()
        if daily_hours is not None:
            if daily_hours < 4:
                diagnosis.items.append(DiagnosisItem(
                    level=DiagnosisLevel.ALERT,
                    category=DiagnosisCategory.LIGHT,
                    title="日照時間 (24h推定)",
                    message=(
                        f"約{daily_hours:.1f}時間 - 日照不足。"
                        f"モロヘイヤは1日6時間以上の直射日光が必要です。"
                    ),
                    value=daily_hours,
                    optimal_range="6時間以上/日",
                ))
                score -= 15
            elif daily_hours < 6:
                diagnosis.items.append(DiagnosisItem(
                    level=DiagnosisLevel.WARNING,
                    category=DiagnosisCategory.LIGHT,
                    title="日照時間 (24h推定)",
                    message=f"約{daily_hours:.1f}時間 - やや不足。6時間以上が理想です。",
                    value=daily_hours,
                    optimal_range="6時間以上/日",
                ))
                score -= 5

        # スコアを 0-100 にクリップ
        diagnosis.score = max(0, min(100, score))

        logger.info(f"栽培診断完了: スコア={diagnosis.score}, items={len(diagnosis.items)}")
        return diagnosis

    def diagnose_from_sensor_data(self, sensor_data) -> PlantDiagnosis:
        """
        SensorReadAll データから診断 (main.py から呼びやすいインターフェース)

        Args:
            sensor_data: ArduinoDriver.read_all() の戻り値
        """
        avg_soil = (
            sum(sensor_data.soil) / len(sensor_data.soil)
            if sensor_data.soil else None
        )
        return self.diagnose(
            soil_moisture=avg_soil,
            temperature=sensor_data.temperature,
            humidity=sensor_data.humidity,
            light_lux=sensor_data.light_lux,
            ec_value=getattr(sensor_data, 'ec_value', None),
        )
