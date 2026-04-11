"""
logger.py - ログ設定

ローテーション付きファイルログ + コンソール出力。
Spreadsheet が落ちていてもローカルにログが残る。
"""

import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(
    level: str = "INFO",
    log_file: str = "logs/watering.log",
    max_bytes: int = 5242880,
    backup_count: int = 3,
) -> None:
    """
    アプリケーション全体のログ設定を行う。

    Args:
        level: ログレベル (DEBUG / INFO / WARNING / ERROR)
        log_file: ログファイルパス (raspi/ からの相対パス)
        max_bytes: ログファイルの最大サイズ
        backup_count: ローテーション保持数
    """
    # ログディレクトリ作成
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # ルートロガー設定
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 既存ハンドラをクリア (重複防止)
    root_logger.handlers.clear()

    # フォーマット
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # コンソールハンドラ
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    # ファイルハンドラ (ローテーション付き)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        root_logger.warning(f"ログファイルを開けません: {e} (コンソールのみ出力)")
