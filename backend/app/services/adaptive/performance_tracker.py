"""
Performance tracker — records signal outcomes when positions close.
Each closed position feeds back into the adaptive learning loop.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def record_outcome(
    *,
    signal_id: int | None,
    ticker: str,
    signal_direction: str,
    composite_score: float,
    news_score: float | None,
    reddit_score: float | None,
    entry_price: float,
    exit_price: float,
    regime: str = "normal",
) -> None:
    """
    Persist one closed-trade outcome and trigger optimization if the
    auto-optimize threshold has been reached.
    """
    if entry_price <= 0 or exit_price <= 0:
        return

    raw_pnl = (exit_price - entry_price) / entry_price
    # For a SELL signal, profit is made when price *falls*
    pnl_pct   = raw_pnl if signal_direction == "BUY" else -raw_pnl
    was_correct = pnl_pct > 0

    from app.db.session import AsyncSessionLocal
    from app.models.adaptive import SignalOutcome

    async with AsyncSessionLocal() as db:
        outcome = SignalOutcome(
            signal_id=signal_id,
            ticker=ticker,
            signal_direction=signal_direction,
            composite_score=composite_score,
            news_score=news_score,
            reddit_score=reddit_score,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=round(pnl_pct, 6),
            was_correct=was_correct,
            regime_at_entry=regime,
        )
        db.add(outcome)
        await db.commit()

    logger.info(
        f"Outcome recorded: {ticker} {signal_direction} "
        f"entry={entry_price:.2f} exit={exit_price:.2f} "
        f"pnl={pnl_pct:+.2%} correct={was_correct}"
    )

    # ── Save LLM training sample from this outcome ────────────────────────
    try:
        from app.services.advisor.training import save_training_sample
        await save_training_sample(
            ticker=ticker,
            direction=signal_direction,
            composite_score=composite_score,
            news_score=news_score,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            was_correct=was_correct,
            regime=regime,
        )
    except Exception as e:
        logger.warning(f"Training sample collection failed: {e}")

    # ── Auto-trigger optimization ─────────────────────────────────────────
    import app.services.adaptive.adaptive_engine as engine
    engine._outcomes_since_last_opt += 1

    if engine._outcomes_since_last_opt >= engine.OPTIMIZE_AFTER_N_OUTCOMES:
        engine._outcomes_since_last_opt = 0
        async with AsyncSessionLocal() as db:
            try:
                await engine.run_optimization(db)
            except Exception as e:
                logger.error(f"Auto-optimization failed: {e}")
