"""
Build structured market context strings to inject into the LLM prompt.

Pulls live data from DB and Alpaca so the advisor always reasons from
current portfolio state, not stale training weights.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

logger = logging.getLogger(__name__)


async def build_portfolio_context(db: AsyncSession) -> str:
    """Full portfolio + recent signals + performance summary."""
    lines: list[str] = []

    # Account info
    try:
        import asyncio
        from app.services.trading_engine.broker import get_account, get_positions
        account, positions = await asyncio.gather(
            asyncio.to_thread(get_account),
            asyncio.to_thread(get_positions),
        )
        lines.append(f"PORTFOLIO EQUITY: ${account['equity']:,.2f}")
        lines.append(f"CASH: ${account['cash']:,.2f}")
        lines.append(f"BUYING POWER: ${account['buying_power']:,.2f}")
        lines.append(f"TRADING MODE: {account.get('trading_mode', 'paper')}")
        if positions:
            lines.append(f"\nOPEN POSITIONS ({len(positions)}):")
            for p in positions[:10]:
                pnl = p['unrealized_pnl']
                sign = '+' if pnl >= 0 else ''
                lines.append(
                    f"  {p['ticker']}: {p['qty']} shares @ ${p['avg_entry_price']:.2f} "
                    f"| current ${p['current_price']:.2f} | PnL {sign}${pnl:.2f}"
                )
        else:
            lines.append("OPEN POSITIONS: none")
    except Exception as e:
        lines.append(f"PORTFOLIO: unavailable ({e})")

    # Recent signals
    try:
        from app.models.signal import Signal
        result = await db.execute(
            select(Signal).order_by(desc(Signal.created_at)).limit(10)
        )
        sigs = result.scalars().all()
        if sigs:
            lines.append("\nRECENT SIGNALS (last 10):")
            for s in sigs:
                ago = _time_ago(s.created_at)
                lines.append(
                    f"  {s.ticker}: {s.direction} score={s.composite_score:+.3f} "
                    f"conf={s.confidence:.2f} [{ago}]"
                )
    except Exception as e:
        logger.warning(f"Could not load signals for context: {e}")

    # Adaptive performance
    try:
        from app.models.adaptive import SignalOutcome
        result = await db.execute(
            select(SignalOutcome).order_by(desc(SignalOutcome.created_at)).limit(50)
        )
        outcomes = result.scalars().all()
        if outcomes:
            wins = sum(1 for o in outcomes if o.was_correct)
            win_rate = wins / len(outcomes) * 100
            pnls = [o.pnl_pct for o in outcomes if o.pnl_pct is not None]
            avg_pnl = sum(pnls) / len(pnls) * 100 if pnls else 0
            lines.append(f"\nSTRATEGY PERFORMANCE (last {len(outcomes)} trades):")
            lines.append(f"  Win rate: {win_rate:.1f}%")
            lines.append(f"  Avg PnL: {avg_pnl:+.2f}%")
    except Exception as e:
        logger.warning(f"Could not load outcomes for context: {e}")

    # Watchlist
    try:
        from app.models.watchlist import Watchlist
        result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
        watchlist = [w.ticker for w in result.scalars().all()]
        if watchlist:
            lines.append(f"\nWATCHLIST: {', '.join(watchlist)}")
    except Exception:
        pass

    return "\n".join(lines)


async def build_ticker_context(ticker: str, db: AsyncSession) -> str:
    """Focused context for a single ticker."""
    lines = [f"TICKER: {ticker}"]

    # Latest signal
    try:
        from app.models.signal import Signal
        result = await db.execute(
            select(Signal)
            .where(Signal.ticker == ticker)
            .order_by(desc(Signal.created_at))
            .limit(5)
        )
        sigs = result.scalars().all()
        if sigs:
            latest = sigs[0]
            lines.append(f"LATEST SIGNAL: {latest.direction} score={latest.composite_score:+.3f}")
            if latest.raw_headlines:
                quant = latest.raw_headlines.get("_quant", {})
                if quant:
                    lines.append(f"  NLP: {quant.get('nlp', 0):+.3f}")
                    lines.append(f"  Momentum (12-1mo): {quant.get('momentum', 0):+.3f}")
                    lines.append(f"  Mean reversion: {quant.get('mean_reversion', 0):+.3f}")
                    lines.append(f"  Technical (RSI/MACD/EMA): {quant.get('technical', 0):+.3f}")
    except Exception:
        pass

    # Recent price
    try:
        import asyncio
        from app.services.market_data.yfinance_client import get_snapshot
        snap = await asyncio.to_thread(get_snapshot, ticker)
        if snap.get("price"):
            lines.append(f"CURRENT PRICE: ${snap['price']:.2f}")
    except Exception:
        pass

    return "\n".join(lines)


def _time_ago(dt) -> str:
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() / 60)}m ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() / 3600)}h ago"
    return f"{delta.days}d ago"
