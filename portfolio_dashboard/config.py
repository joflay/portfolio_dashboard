from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    app_key: str
    app_secret: str
    region: str
    endpoint: str
    token_file: Path
    data_dir: Path
    database_path: Path
    market_data_dir: Path
    dashboard_host: str
    dashboard_port: int
    sync_interval_minutes: int
    account_info_file: Path
    account_list_path: str
    account_positions_path: str
    order_history_path: str


def load_settings() -> Settings:
    env_file = _load_dotenv(BASE_DIR / ".env")

    def get(name: str, default: str = "") -> str:
        return os.environ.get(name, env_file.get(name, default))

    data_dir = Path(get("DATA_DIR", str(BASE_DIR / "data"))).expanduser()
    return Settings(
        app_key=get("WEBULL_APP_KEY"),
        app_secret=get("WEBULL_APP_SECRET"),
        region=get("WEBULL_REGION", "US"),
        endpoint=_normalize_endpoint(get("WEBULL_ENDPOINT", "https://api.webull.com")),
        token_file=Path(get("WEBULL_TOKEN_FILE", str(BASE_DIR / "conf" / "token.txt"))).expanduser(),
        data_dir=data_dir,
        database_path=Path(get("DATABASE_PATH", str(data_dir / "portfolio.db"))).expanduser(),
        market_data_dir=Path(get("MARKET_DATA_DIR", "/srv/data/stocks")).expanduser(),
        dashboard_host=get("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=int(get("DASHBOARD_PORT", "8080")),
        sync_interval_minutes=int(get("SYNC_INTERVAL_MINUTES", "15")),
        account_info_file=Path(get("WEBULL_ACCOUNT_INFO_FILE", str(BASE_DIR / "accouninfo.txt"))).expanduser(),
        account_list_path=get("WEBULL_ACCOUNT_LIST_PATH", "/openapi/account/list"),
        account_positions_path=get("WEBULL_ACCOUNT_POSITIONS_PATH", "/openapi/assets/positions"),
        order_history_path=get("WEBULL_ORDER_HISTORY_PATH", "/openapi/trade/order/history"),
    )


def _normalize_endpoint(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    if not value:
        return "https://api.webull.com"
    if "://" not in value:
        value = f"https://{value}"
    return value
