"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
import warnings
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
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    max_upload_mb: int = 30
    moengage_mode: str = "browser"
    allow_mock_writes: bool = False
    moengage_timeout_seconds: float = 30.0
    moengage_max_retries: int = 2
    moengage_brand_config: dict[str, dict[str, Any]] = field(default_factory=dict)
    moengage_dashboard_url: str = "https://dashboard.moengage.com/"
    moengage_ui_config: dict[str, Any] = field(default_factory=dict)
    google_service_account_file: Path = BASE_DIR / "credentials" / "google-service-account.json"
    google_service_account_json: str = ""
    google_spreadsheet_url: str = ""
    google_worksheet_name: str = "Mastersheet"

    @classmethod
    def from_env(cls) -> "Settings":
        raw_config = os.getenv("MOENGAGE_BRAND_CONFIG_JSON", "{}")
        try:
            brand_config = json.loads(raw_config)
        except json.JSONDecodeError:
            warnings.warn(
                "Ignoring invalid MOENGAGE_BRAND_CONFIG_JSON; configure valid JSON before using API mode",
                RuntimeWarning,
            )
            brand_config = {}
        if not isinstance(brand_config, dict):
            warnings.warn(
                "Ignoring MOENGAGE_BRAND_CONFIG_JSON because it is not a JSON object",
                RuntimeWarning,
            )
            brand_config = {}
        try:
            ui_config = json.loads(os.getenv("MOENGAGE_UI_CONFIG_JSON", "{}"))
        except json.JSONDecodeError:
            warnings.warn(
                "Ignoring invalid MOENGAGE_UI_CONFIG_JSON",
                RuntimeWarning,
            )
            ui_config = {}
        if not isinstance(ui_config, dict):
            warnings.warn(
                "Ignoring MOENGAGE_UI_CONFIG_JSON because it is not a JSON object",
                RuntimeWarning,
            )
            ui_config = {}
        credential_path = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/google-service-account.json"))
        if not credential_path.is_absolute():
            credential_path = BASE_DIR / credential_path
        storage_path = Path(
            os.getenv("STORAGE_DIR")
            or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
            or BASE_DIR / "storage"
        )
        raw_origins = os.getenv("CORS_ORIGINS", "").strip()
        if raw_origins:
            if raw_origins.startswith("["):
                try:
                    parsed_origins = json.loads(raw_origins)
                except json.JSONDecodeError:
                    warnings.warn("Ignoring invalid CORS_ORIGINS JSON", RuntimeWarning)
                    parsed_origins = []
                if not isinstance(parsed_origins, list):
                    warnings.warn("Ignoring CORS_ORIGINS because it is not a JSON array", RuntimeWarning)
                    parsed_origins = []
                cors_origins = [str(origin).strip().rstrip("/") for origin in parsed_origins]
            else:
                cors_origins = [origin.strip().rstrip("/") for origin in raw_origins.split(",")]
            cors_origins = [origin for origin in cors_origins if origin]
        else:
            cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().strip("/")
        if railway_domain:
            railway_origin = f"https://{railway_domain}"
            if railway_origin not in cors_origins:
                cors_origins.append(railway_origin)
        return cls(
            storage_dir=storage_path,
            cors_origins=tuple(cors_origins),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "30")),
            moengage_mode=os.getenv("MOENGAGE_MODE", "browser").lower(),
            allow_mock_writes=os.getenv("ALLOW_MOCK_WRITES", "false").lower() in {"1", "true", "yes"},
            moengage_timeout_seconds=float(os.getenv("MOENGAGE_TIMEOUT_SECONDS", "30")),
            moengage_max_retries=int(os.getenv("MOENGAGE_MAX_RETRIES", "2")),
            moengage_brand_config=brand_config,
            moengage_dashboard_url=os.getenv("MOENGAGE_DASHBOARD_URL", "https://dashboard.moengage.com/"),
            moengage_ui_config=ui_config,
            google_service_account_file=credential_path,
            google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
            google_spreadsheet_url=os.getenv("GOOGLE_SPREADSHEET_URL", "").strip(),
            google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "Mastersheet").strip() or "Mastersheet",
        )


settings = Settings.from_env()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
(settings.storage_dir / "uploads").mkdir(exist_ok=True)
(settings.storage_dir / "outputs").mkdir(exist_ok=True)
(settings.storage_dir / "moengage-profile").mkdir(exist_ok=True)
