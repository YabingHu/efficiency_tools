"""加载 config.yaml 与 .env。"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = str(PROJECT_ROOT)
    return cfg


def get_api_key() -> str:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key or key.startswith("sk-xxxx"):
        raise RuntimeError(
            "未配置 API key：请复制 .env.example 为 .env 并填入 LLM_API_KEY"
        )
    return key
