"""載入 .env(若存在)。所有模組 import src.config 即完成環境設定。"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
