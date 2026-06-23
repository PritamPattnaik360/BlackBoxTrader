import asyncio
import logging
from app.config import settings
from app.services.market_data.cache import set_quote, publish_quote

logger = logging.getLogger(__name__)
_stream = None
_subscribed_tickers: set[str] = set()


async def start_stream(tickers: list[str]) -> None:
    global _stream, _subscribed_tickers
    if not settings.alpaca_api_key:
        logger.warning("Alpaca API key not set — market data stream disabled")
        return
    try:
        from alpaca.data.live import StockDataStream
        from alpaca.data.models import Bar

        _stream = StockDataStream(settings.alpaca_api_key, settings.alpaca_secret_key)

        async def on_bar(bar: Bar):
            data = {
                "ticker": bar.symbol,
                "time": bar.timestamp.isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
            }
            set_quote(bar.symbol, data)
            publish_quote(bar.symbol, data)

        _stream.subscribe_bars(on_bar, *tickers)
        _subscribed_tickers = set(tickers)
        asyncio.create_task(_stream.run())
        logger.info(f"Alpaca stream started for {tickers}")
    except Exception as e:
        logger.error(f"Failed to start Alpaca stream: {e}")


async def stop_stream() -> None:
    global _stream
    if _stream:
        try:
            await _stream.stop()
        except Exception:
            pass
        _stream = None


async def add_ticker(ticker: str) -> None:
    global _stream, _subscribed_tickers
    if _stream and ticker not in _subscribed_tickers:
        from alpaca.data.models import Bar

        async def on_bar(bar: Bar):
            data = {
                "ticker": bar.symbol,
                "time": bar.timestamp.isoformat(),
                "close": float(bar.close),
                "volume": int(bar.volume),
            }
            set_quote(bar.symbol, data)
            publish_quote(bar.symbol, data)

        _stream.subscribe_bars(on_bar, ticker)
        _subscribed_tickers.add(ticker)
