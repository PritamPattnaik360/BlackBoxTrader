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

    # NLP — absolute path so it works regardless of CWD
    finbert_model_path: str = str(Path(__file__).parents[2] / "data" / "models" / "finbert")
    finbert_batch_size: int = 32

    # Scheduler intervals (seconds)
    signal_scan_interval: int = 300      # 5 minutes (intraday)
    portfolio_sync_interval: int = 60    # 1 minute
    order_poll_interval: int = 30        # 30 seconds

    # Risk defaults
    max_position_pct: float = 0.10       # 10% of portfolio per position
    max_drawdown_halt_pct: float = 0.15  # halt if 15% below peak
    daily_loss_halt_pct: float = 0.05    # halt if day P&L < -5%
    market_crash_halt_pct: float = 0.03  # halt if SPY is down 3%+ on the day
    flatten_on_halt: bool = True         # liquidate all positions when the breaker trips
    position_max_loss_pct: float = 0.15  # hard stop: close any stock position down 15%
    option_max_loss_pct: float = 0.50    # hard stop: close any option position down 50%
    risk_guard_interval: int = 30        # seconds between circuit-breaker checks
    risk_per_trade_pct: float = 0.01     # 1% of equity risked per trade
    max_open_positions: int = 20
    default_stop_atr_multiplier: float = 2.0
    options_target_dte: int = 30

    # Options trading — off by default. When enabled, BUY signals open long
    # calls and SELL signals open long puts (still no short-selling — a
    # bearish view is expressed by buying a put, not shorting shares).
    enable_options_trading: bool = False

    # Day-trade-only mode (default): autonomous BUYs are only opened as intraday
    # trades � tight stop, same-day take-profit, flattened before the close � and
    # never held overnight. Set DAY_TRADE_ONLY=false to also allow multi-day swing positions.
    day_trade_only: bool = True

    # Hard entry gates for day trades, applied in the executor so neither the bias
    # profiles' threshold discounts nor the nightly learner can loosen them.
    # Paper journal 2026-10-09..21: entries scoring < 0.30 lost $1,074 over 14 trades.
    # Entries scoring >= 0.30 were profitable at every hour, so the cutoff defaults to the
    # existing 15:30 window end; tighten it only if more data shows late entries losing.
    day_trade_min_score: float = 0.30
    day_trade_entry_cutoff: str = "15:30"   # ET, HH:MM; no new day-trade entries after this
    # VWAP confirmation: intraday_vwap is tanh(30 x % above session VWAP), so 0.35 means price
    # is ~1.2%+ above VWAP. Journal 2026-10-09..22 (score >= 0.30): below it 46% wins and
    # -$291; at/above it 65% wins and +$2,103.
    day_trade_min_vwap: float = 0.35

    # Force one small trade per scan when nothing qualifies, to seed learning outcomes.
    # Off by default: those sub-threshold trades were the biggest P&L drain.
    force_learning_trade: bool = False

    # Local LLM trading signal (Ollama). Paused by default: ~15s/ticker made scans overrun
    # their interval, and the quant algorithms carry the trading decision. When True it
    # still only runs during market hours. The advisor chat is unaffected.
    llm_signal_enabled: bool = False

    # Nightly self-learning (component weights + day-trade stop/target tuning).
    # See app/services/adaptive/daily_learner.py. Set LEARNING_ENABLED=false to freeze the algos.
    learning_enabled: bool = True

    # Short-selling day trades in BEARISH markets. When the market bias is "bear", strong
    # intraday breakdowns are shorted (stop above, take-profit below, covered by 15:50 ET) and
    # a bounce is never held overnight. Needs an Alpaca account with shorting enabled and a
    # shortable, easy-to-borrow stock. In LIVE mode it also needs ALLOW_SHORT_LIVE=true.
    enable_short_day_trades: bool = True
    allow_short_live: bool = False

    # Autonomous trading — set AUTO_START_AUTONOMOUS=true in .env to enable on boot
    auto_start_autonomous: bool = False

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
