from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

# Always resolve .env relative to this file (backend/.env) regardless of cwd
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Explicitly load .env into os.environ BEFORE pydantic-settings reads them.
# This guarantees keys are available even if pydantic-settings env_file parsing
# silently skips the file (e.g. encoding, reload, or version quirks).
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(_ENV_FILE), override=False)
except Exception:
    pass  # dotenv is optional; pydantic-settings env_file is the fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    trading_mode: Literal["paper", "live"] = "paper"

    # Database
    use_sqlite: bool = True
    database_url: str = "sqlite+aiosqlite:///./blackbox.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = False  # graceful fallback to in-memory cache

    # News APIs
    newsapi_key: str = ""
    gnews_api_key: str = ""

    # NLP
    finbert_model_path: str = "../data/models/finbert"
    finbert_batch_size: int = 32

    # Scheduler intervals (seconds)
    signal_scan_interval: int = 900      # 15 minutes
    portfolio_sync_interval: int = 60    # 1 minute
    order_poll_interval: int = 30        # 30 seconds

    # Risk defaults
    max_position_pct: float = 0.10       # 10% of portfolio per position
    max_drawdown_halt_pct: float = 0.15  # halt if 15% below peak
    daily_loss_halt_pct: float = 0.05    # halt if day P&L < -5%
    risk_per_trade_pct: float = 0.01     # 1% of equity risked per trade
    max_open_positions: int = 20
    default_stop_atr_multiplier: float = 2.0
    options_target_dte: int = 30

    # Signal thresholds
    buy_signal_threshold: float = 0.3
    sell_signal_threshold: float = -0.3

    @property
    def alpaca_base_url(self) -> str:
        if self.trading_mode == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    @property
    def alpaca_data_url(self) -> str:
        return "https://data.alpaca.markets"


settings = Settings()
