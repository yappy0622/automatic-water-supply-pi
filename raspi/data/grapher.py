"""
grapher.py - センサーデータグラフ生成

sensor_log.py が蓄積した CSV を読み込み、matplotlib で推移グラフを生成する。
生成したグラフは Discord 通知や Web ダッシュボードに利用できる。

生成するグラフ:
  1. 土壌湿度の推移 (2系列: センサー1, センサー2 + 閾値ライン)
  2. 温度・湿度の推移 (2軸)
  3. 照度の推移
  4. EC (土壌電気伝導度) の推移
  5. 全センサー統合ダッシュボード (5パネル)

使用例:
    grapher = SensorGrapher(csv_path="logs/sensor_data.csv")
    path = grapher.generate_all()            # 統合グラフ
    path = grapher.generate_soil_graph()     # 土壌のみ
    path = grapher.generate_climate_graph()  # 温湿度のみ
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import matplotlib

    matplotlib.use("Agg")  # ヘッドレス環境用
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.info("matplotlib/pandas がインストールされていません。グラフ生成は無効です。")


# グラフ出力ディレクトリ
DEFAULT_GRAPH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "graphs")


class SensorGrapher:
    """センサーデータのグラフ生成器"""

    def __init__(
        self,
        csv_path: str,
        graph_dir: str = DEFAULT_GRAPH_DIR,
        soil_threshold: int = 400,
        days: int = 7,
    ):
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError(
                "matplotlib / pandas がインストールされていません。\n"
                "  pip install matplotlib pandas"
            )

        self._csv_path = csv_path
        self._graph_dir = graph_dir
        self._soil_threshold = soil_threshold
        self._days = days

        os.makedirs(graph_dir, exist_ok=True)

        # 日本語フォントの設定 (フォールバック)
        plt.rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]
        plt.rcParams["axes.unicode_minus"] = False

    def set_threshold(self, threshold: int) -> None:
        """閾値を更新 (ConfigManager から呼ばれる)"""
        self._soil_threshold = threshold

    # =========================================================================
    # CSV 読み込み
    # =========================================================================

    def _load_csv(self, days: Optional[int] = None) -> "pd.DataFrame":
        """CSV を読み込み、最近 N 日分にフィルタリング"""
        if not os.path.exists(self._csv_path):
            logger.warning(f"CSV ファイルが見つかりません: {self._csv_path}")
            return pd.DataFrame()

        df = pd.read_csv(
            self._csv_path,
            parse_dates=["timestamp"],
            encoding="utf-8",
        )

        if df.empty:
            return df

        # 数値型に変換
        for col in ["soil_1", "soil_2", "temperature", "humidity", "light_lux", "ec"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 直近 N 日間でフィルタ
        if days is None:
            days = self._days
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff]

        return df.sort_values("timestamp").reset_index(drop=True)

    # =========================================================================
    # 個別グラフ生成
    # =========================================================================

    def generate_soil_graph(self, days: Optional[int] = None) -> Optional[str]:
        """
        土壌湿度の推移グラフを生成。

        Returns:
            生成された画像ファイルのパス (失敗時 None)
        """
        df = self._load_csv(days)
        if df.empty or "soil_1" not in df.columns:
            logger.info("土壌湿度データがありません")
            return None

        fig, ax = plt.subplots(figsize=(12, 5))

        ax.plot(df["timestamp"], df["soil_1"], label="Sensor 1", color="#2196F3", linewidth=1.5)
        if "soil_2" in df.columns and df["soil_2"].notna().any():
            ax.plot(df["timestamp"], df["soil_2"], label="Sensor 2", color="#4CAF50", linewidth=1.5)

        # 閾値ライン
        ax.axhline(
            y=self._soil_threshold,
            color="#FF5722",
            linestyle="--",
            linewidth=1,
            label=f"Threshold ({self._soil_threshold})",
        )

        # 乾燥ゾーンのハイライト
        ax.axhspan(0, self._soil_threshold, alpha=0.05, color="red")

        ax.set_title("Soil Moisture Trend", fontsize=14, fontweight="bold")
        ax.set_xlabel("Time")
        ax.set_ylabel("Moisture (0=dry, 1023=wet)")
        ax.set_ylim(0, 1023)
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        fig.autofmt_xdate()

        path = os.path.join(self._graph_dir, "soil_moisture.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"土壌湿度グラフ生成: {path}")
        return path

    def generate_climate_graph(self, days: Optional[int] = None) -> Optional[str]:
        """
        温度・湿度の推移グラフ (2軸) を生成。

        Returns:
            生成された画像ファイルのパス
        """
        df = self._load_csv(days)
        if df.empty or "temperature" not in df.columns:
            logger.info("温湿度データがありません")
            return None

        fig, ax1 = plt.subplots(figsize=(12, 5))

        # 温度 (左軸)
        color_temp = "#FF5722"
        ax1.plot(
            df["timestamp"],
            df["temperature"],
            label="Temperature",
            color=color_temp,
            linewidth=1.5,
        )
        ax1.set_xlabel("Time")
        ax1.set_ylabel("Temperature (C)", color=color_temp)
        ax1.tick_params(axis="y", labelcolor=color_temp)

        # 湿度 (右軸)
        ax2 = ax1.twinx()
        color_hum = "#2196F3"
        ax2.plot(
            df["timestamp"],
            df["humidity"],
            label="Humidity",
            color=color_hum,
            linewidth=1.5,
            linestyle="--",
        )
        ax2.set_ylabel("Humidity (%)", color=color_hum)
        ax2.tick_params(axis="y", labelcolor=color_hum)

        ax1.set_title("Temperature & Humidity Trend", fontsize=14, fontweight="bold")
        ax1.grid(True, alpha=0.3)

        # 凡例を結合
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        fig.autofmt_xdate()

        path = os.path.join(self._graph_dir, "climate.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"温湿度グラフ生成: {path}")
        return path

    def generate_ec_graph(self, days: Optional[int] = None) -> Optional[str]:
        """EC (土壌電気伝導度) の推移グラフを生成"""
        df = self._load_csv(days)
        if df.empty or "ec" not in df.columns or df["ec"].isna().all():
            logger.info("ECデータがありません")
            return None

        fig, ax = plt.subplots(figsize=(12, 5))

        ax.fill_between(
            df["timestamp"],
            df["ec"],
            alpha=0.3,
            color="#9C27B0",
        )
        ax.plot(
            df["timestamp"],
            df["ec"],
            color="#7B1FA2",
            linewidth=1.5,
            label="EC (mS/cm)",
        )

        # モロヘイヤの最適範囲を表示 (0.5〜2.0 mS/cm)
        ax.axhspan(0.5, 2.0, alpha=0.08, color="green", label="Optimal range (0.5-2.0)")
        ax.axhline(y=0.5, color="#4CAF50", linestyle=":", linewidth=0.8, alpha=0.6)
        ax.axhline(y=2.0, color="#4CAF50", linestyle=":", linewidth=0.8, alpha=0.6)

        ax.set_title("Soil EC (Electrical Conductivity) Trend", fontsize=14, fontweight="bold")
        ax.set_xlabel("Time")
        ax.set_ylabel("EC (mS/cm)")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        fig.autofmt_xdate()

        path = os.path.join(self._graph_dir, "ec.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"ECグラフ生成: {path}")
        return path

    def generate_light_graph(self, days: Optional[int] = None) -> Optional[str]:
        """照度の推移グラフを生成"""
        df = self._load_csv(days)
        if df.empty or "light_lux" not in df.columns or df["light_lux"].isna().all():
            logger.info("照度データがありません")
            return None

        fig, ax = plt.subplots(figsize=(12, 5))

        ax.fill_between(
            df["timestamp"],
            df["light_lux"],
            alpha=0.3,
            color="#FFC107",
        )
        ax.plot(
            df["timestamp"],
            df["light_lux"],
            color="#FF9800",
            linewidth=1.5,
        )

        ax.set_title("Light Intensity Trend", fontsize=14, fontweight="bold")
        ax.set_xlabel("Time")
        ax.set_ylabel("Illuminance (lux)")
        ax.grid(True, alpha=0.3)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        fig.autofmt_xdate()

        path = os.path.join(self._graph_dir, "light.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"照度グラフ生成: {path}")
        return path

    # =========================================================================
    # 統合ダッシュボード
    # =========================================================================

    def generate_all(self, days: Optional[int] = None) -> Optional[str]:
        """
        全センサーの統合ダッシュボードグラフを生成 (4パネル)。

        Returns:
            生成された画像ファイルのパス
        """
        df = self._load_csv(days)
        if df.empty:
            logger.info("グラフ生成: データがありません")
            return None

        has_soil = "soil_1" in df.columns and df["soil_1"].notna().any()
        has_climate = "temperature" in df.columns and df["temperature"].notna().any()
        has_light = "light_lux" in df.columns and df["light_lux"].notna().any()
        has_ec = "ec" in df.columns and df["ec"].notna().any()
        has_water = "water_ok" in df.columns

        # パネル数を動的に決定
        panels = []
        if has_soil:
            panels.append("soil")
        if has_climate:
            panels.append("climate")
        if has_light:
            panels.append("light")
        if has_ec:
            panels.append("ec")
        if has_water:
            panels.append("water")

        n_panels = max(len(panels), 1)
        fig, axes = plt.subplots(n_panels, 1, figsize=(14, 4 * n_panels), sharex=True)
        if n_panels == 1:
            axes = [axes]

        panel_idx = 0

        # --- 土壌湿度パネル ---
        if has_soil:
            ax = axes[panel_idx]
            ax.plot(df["timestamp"], df["soil_1"], label="Sensor 1", color="#2196F3", linewidth=1.2)
            if "soil_2" in df.columns and df["soil_2"].notna().any():
                ax.plot(df["timestamp"], df["soil_2"], label="Sensor 2", color="#4CAF50", linewidth=1.2)
            ax.axhline(y=self._soil_threshold, color="#FF5722", linestyle="--", linewidth=1, label=f"Threshold ({self._soil_threshold})")
            ax.axhspan(0, self._soil_threshold, alpha=0.05, color="red")
            ax.set_ylabel("Soil Moisture")
            ax.set_ylim(0, 1023)
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_title("Soil Moisture", fontsize=11, fontweight="bold")
            panel_idx += 1

        # --- 温湿度パネル ---
        if has_climate:
            ax = axes[panel_idx]
            ax.plot(df["timestamp"], df["temperature"], label="Temperature (C)", color="#FF5722", linewidth=1.2)
            ax2 = ax.twinx()
            ax2.plot(df["timestamp"], df["humidity"], label="Humidity (%)", color="#2196F3", linewidth=1.2, linestyle="--")
            ax.set_ylabel("Temperature (C)")
            ax2.set_ylabel("Humidity (%)")
            lines1, labels1 = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_title("Temperature & Humidity", fontsize=11, fontweight="bold")
            panel_idx += 1

        # --- 照度パネル ---
        if has_light:
            ax = axes[panel_idx]
            ax.fill_between(df["timestamp"], df["light_lux"], alpha=0.3, color="#FFC107")
            ax.plot(df["timestamp"], df["light_lux"], color="#FF9800", linewidth=1.2)
            ax.set_ylabel("Light (lux)")
            ax.grid(True, alpha=0.3)
            ax.set_title("Light Intensity", fontsize=11, fontweight="bold")
            panel_idx += 1

        # --- ECパネル ---
        if has_ec:
            ax = axes[panel_idx]
            ax.fill_between(df["timestamp"], df["ec"], alpha=0.3, color="#9C27B0")
            ax.plot(df["timestamp"], df["ec"], color="#7B1FA2", linewidth=1.2, label="EC (mS/cm)")
            ax.axhspan(0.5, 2.0, alpha=0.08, color="green")
            ax.axhline(y=0.5, color="#4CAF50", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.axhline(y=2.0, color="#4CAF50", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.set_ylabel("EC (mS/cm)")
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_title("Soil EC (Electrical Conductivity)", fontsize=11, fontweight="bold")
            panel_idx += 1

        # --- 水位パネル ---
        if has_water:
            ax = axes[panel_idx]
            water_numeric = df["water_ok"].astype(str).map({"1": 1, "0": 0, "True": 1, "False": 0}).fillna(0)
            ax.fill_between(df["timestamp"], water_numeric, step="post", alpha=0.4, color="#4CAF50")
            ax.step(df["timestamp"], water_numeric, where="post", color="#4CAF50", linewidth=1.2)
            ax.set_ylabel("Water Level")
            ax.set_ylim(-0.1, 1.1)
            ax.set_yticks([0, 1])
            ax.set_yticklabels(["Empty", "OK"])
            ax.grid(True, alpha=0.3)
            ax.set_title("Water Level", fontsize=11, fontweight="bold")
            panel_idx += 1

        # X 軸のフォーマット
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        axes[-1].set_xlabel("Time")

        fig.suptitle(
            f"Sensor Dashboard (Last {days or self._days} days)",
            fontsize=14,
            fontweight="bold",
            y=1.01,
        )
        fig.tight_layout()
        fig.autofmt_xdate()

        path = os.path.join(self._graph_dir, "dashboard.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"統合ダッシュボード生成: {path}")

        # 個別グラフも同時生成
        self.generate_soil_graph(days)
        self.generate_climate_graph(days)
        self.generate_light_graph(days)
        self.generate_ec_graph(days)

        return path
