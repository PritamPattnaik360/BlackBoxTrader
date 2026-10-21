import asyncio
import logging
from app.config import settings
from app.services.market_data.cache import set_quote, publish_quote

logger = logging.getLogger(__name__)
_stream = None
_stream_task: asyncio.Task | None = None
_subscribed_tickers: set[str] = set()


def _on_stream_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Alpaca stream stopped unexpectedly: {exc!r}")


async def start_stream(tickers: list[str]) -> None:
    global _stream, _stream_task, _subscribed_tickers
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
            set_quote(bar.symbol, data, ttl=300)   # bars arrive ~1/min; keep the last one around
            publish_quote(bar.symbol, data)

        _stream.subscribe_bars(on_bar, *tickers)
        _subscribed_tickers = set(tickers)
        # StockDataStream.run() is blocking and starts its own event loop via
        # asyncio.run(), which can't be called inside FastAPI's running loop (and its
        # cleanup then fails with "'NoneType' object has no attribute 'is_running'").
        # Inside an existing loop, run the stream's coroutine as a task instead.
        _stream_task = asyncio.create_task(_stream._run_forever())
        _stream_task.add_done_callback(_on_stream_done)
        logger.info(f"Alpaca stream started for {tickers}")
    except Exception as e:
        logger.error(f"Failed to start Alpaca stream: {e}")


async def stop_stream() -> None:
    global _stream, _stream_task
    if _stream:
        try:
            await _stream.stop_ws()   # async, safe inside the running loop (stop() is sync)
            if _stream_task:
                await asyncio.wait_for(_stream_task, timeout=5)
        except Exception:
            if _stream_task:
                _stream_task.cancel()
        _stream = None
        _stream_task = None


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
            set_quote(bar.symbol, data, ttl=300)
            publish_quote(bar.symbol, data)

        _stream.subscribe_bars(on_bar, ticker)
        _subscribed_tickers.add(ticker)
