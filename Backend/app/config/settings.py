"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "MoEngage Attribution Automation"
    api_prefix: str = "/api"
    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 30
    moengage_mode: str = "browser"
    moengage_timeout_seconds: float = 30.0
    moengage_max_retries: int = 2
    moengage_brand_config: dict[str, dict[str, Any]] = field(default_factory=dict)
    moengage_dashboard_url: str = "https://dashboard.moengage.com/"
    moengage_ui_config: dict[str, Any] = field(default_factory=dict)
    google_service_account_file: Path = BASE_DIR / "credentials" / "google-service-account.json"
    google_spreadsheet_url: str = ""
    google_worksheet_name: str = "Mastersheet"

    @classmethod
    def from_env(cls) -> "Settings":
        raw_config = os.getenv("MOENGAGE_BRAND_CONFIG_JSON", "{}")
        try:
            brand_config = json.loads(raw_config)
        except json.JSONDecodeError as exc:
            raise RuntimeError("MOENGAGE_BRAND_CONFIG_JSON must be valid JSON") from exc
        if not isinstance(brand_config, dict):
            raise RuntimeError("MOENGAGE_BRAND_CONFIG_JSON must be a JSON object")
        try:
            ui_config = json.loads(os.getenv("MOENGAGE_UI_CONFIG_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("MOENGAGE_UI_CONFIG_JSON must be valid JSON") from exc
        credential_path = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/google-service-account.json"))
        if not credential_path.is_absolute():
            credential_path = BASE_DIR / credential_path
        return cls(
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "30")),
            moengage_mode=os.getenv("MOENGAGE_MODE", "browser").lower(),
            moengage_timeout_seconds=float(os.getenv("MOENGAGE_TIMEOUT_SECONDS", "30")),
            moengage_max_retries=int(os.getenv("MOENGAGE_MAX_RETRIES", "2")),
            moengage_brand_config=brand_config,
            moengage_dashboard_url=os.getenv("MOENGAGE_DASHBOARD_URL", "https://dashboard.moengage.com/"),
            moengage_ui_config=ui_config,
            google_service_account_file=credential_path,
            google_spreadsheet_url=os.getenv("GOOGLE_SPREADSHEET_URL", "").strip(),
            google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "Mastersheet").strip() or "Mastersheet",
        )


settings = Settings.from_env()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
(settings.storage_dir / "uploads").mkdir(exist_ok=True)
(settings.storage_dir / "outputs").mkdir(exist_ok=True)
(settings.storage_dir / "moengage-profile").mkdir(exist_ok=True)
