"""
Main advisor service.

Orchestrates:
  1. Building context from the live DB state
  2. Calling the Ollama LLM
  3. Saving training samples from trade outcomes
  4. Exposing a training data export for fine-tuning
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.services.advisor import llm_client, context_builder
from app.models.advisor import LlmTrainingSample, AdvisorConversation

logger = logging.getLogger(__name__)


# ── Chat ─────────────────────────────────────────────────────────────────────

async def chat(
    message: str,
    session_id: str,
    db: AsyncSession,
    model: str = llm_client.DEFAULT_MODEL,
    ticker: str | None = None,
) -> dict:
    """
    Send a message to the advisor and persist the conversation.
    Returns {"reply": str, "session_id": str}.
    """
    # Load conversation history
    result = await db.execute(
        select(AdvisorConversation)
        .where(AdvisorConversation.session_id == session_id)
        .order_by(AdvisorConversation.created_at)
        .limit(20)
    )
    history_rows = result.scalars().all()
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    # Build context
    if ticker:
        ctx = await context_builder.build_ticker_context(ticker, db)
    else:
        ctx = await context_builder.build_portfolio_context(db)

    # Call LLM
    reply = await llm_client.chat(message, context=ctx, model=model, history=history)

    # Persist turns
    db.add(AdvisorConversation(session_id=session_id, role="user", content=message))
    db.add(AdvisorConversation(session_id=session_id, role="assistant", content=reply))
    await db.commit()

    return {"reply": reply, "session_id": session_id}


# ── Training sample collection ────────────────────────────────────────────────

async def collect_training_sample_from_outcome(
    outcome,   # SignalOutcome ORM instance
    db: AsyncSession,
) -> None:
    """
    Convert a closed trade outcome into a training sample and store it in DB.

    Called automatically by performance_tracker.record_outcome() after every
    closed trade, so the training dataset grows passively as BlackBoxTrader trades.
    """
    try:
        direction = outcome.direction or "HOLD"
        scores = outcome.signal_scores or {}
        regime = outcome.regime_at_entry or "normal"
        entry  = outcome.entry_price or 0
        exit_  = outcome.exit_price or 0
        pnl    = outcome.pnl_pct or 0
        correct = outcome.was_correct

        instruction = (
            f"Analyze this trade signal for {outcome.ticker}:\n"
            f"Direction: {direction}\n"
            f"Signal scores: NLP={scores.get('nlp', 0):+.3f}, "
            f"Momentum={scores.get('momentum', 0):+.3f}, "
            f"Mean reversion={scores.get('mean_reversion', 0):+.3f}, "
            f"Technical={scores.get('technical', 0):+.3f}\n"
            f"Market regime: {regime}\n"
            f"Entry price: ${entry:.2f}\n"
            f"Should I take this {direction} trade on {outcome.ticker}?"
        )

        if correct:
            outcome_word = "profitable"
            pnl_str = f"+{pnl*100:.2f}%" if pnl >= 0 else f"{pnl*100:.2f}%"
            response = (
                f"Yes, this {direction} trade on {outcome.ticker} was the right call. "
                f"The position closed {outcome_word} at {pnl_str} PnL. "
                f"The signal alignment (NLP={scores.get('nlp', 0):+.3f}, "
                f"Momentum={scores.get('momentum', 0):+.3f}) during a {regime} regime "
                f"correctly predicted the move. "
                f"This setup is worth taking when similar conditions align."
            )
        else:
            pnl_str = f"{pnl*100:.2f}%"
            response = (
                f"This {direction} trade on {outcome.ticker} was a losing trade ({pnl_str} PnL). "
                f"In hindsight, the signal was not strong enough — "
                f"NLP={scores.get('nlp', 0):+.3f}, Momentum={scores.get('momentum', 0):+.3f}. "
                f"In a {regime} regime, be more conservative with these thresholds. "
                f"Wait for stronger signal alignment before entering."
            )

        quality = min(abs(pnl) * 20 + 0.3, 1.0)  # bigger pnl = higher quality sample

        db.add(LlmTrainingSample(
            instruction=instruction,
            response=response,
            ticker=outcome.ticker,
            quality=quality,
            was_correct=correct,
            pnl_pct=pnl,
            source="trade_outcome",
            metadata_={
                "direction": direction,
                "regime": regime,
                "scores": scores,
            },
        ))
        await db.commit()
        logger.debug(f"Training sample saved for {outcome.ticker} ({direction}, correct={correct})")
    except Exception as e:
        logger.warning(f"Could not save training sample: {e}")


async def collect_training_sample_from_signal(
    ticker: str,
    signal_scores: dict,
    combined_score: float,
    direction: str,
    regime: str,
    db: AsyncSession,
) -> None:
    """
    Save a training sample when the advisor explains a signal in real time.
    These are 'explanation' samples: they teach the LLM to reason about signals.
    """
    try:
        ctx_parts = []
        for k, v in signal_scores.items():
            ctx_parts.append(f"{k.replace('_', ' ').title()}={v:+.3f}")

        instruction = (
            f"Explain the current {direction} signal for {ticker}.\n"
            f"Combined score: {combined_score:+.3f}\n"
            f"Components: {', '.join(ctx_parts)}\n"
            f"Market regime: {regime}"
        )

        # Build a quant-style explanation
        dominant = max(signal_scores, key=lambda k: abs(signal_scores.get(k, 0)), default="")
        strength = "strong" if abs(combined_score) > 0.5 else "moderate" if abs(combined_score) > 0.3 else "weak"

        response = (
            f"The {strength} {direction} signal for {ticker} is driven primarily by "
            f"{dominant.replace('_', ' ')} ({signal_scores.get(dominant, 0):+.3f}). "
            f"Combined score of {combined_score:+.3f} "
            f"{'exceeds' if direction != 'HOLD' else 'falls below'} the execution threshold. "
            f"In a {regime} market regime, {'this signal type has historically been reliable' if strength == 'strong' else 'wait for confirmation before entering'}."
        )

        db.add(LlmTrainingSample(
            instruction=instruction,
            response=response,
            ticker=ticker,
            quality=0.6,
            source="signal_explanation",
            metadata_={"scores": signal_scores, "combined": combined_score},
        ))
        await db.commit()
    except Exception as e:
        logger.warning(f"Could not save signal training sample: {e}")


# ── Quick analysis ─────────────────────────────────────────────────────────────

async def analyze_portfolio(db: AsyncSession, model: str = llm_client.DEFAULT_MODEL) -> str:
    """One-shot portfolio review. No conversation history."""
    ctx = await context_builder.build_portfolio_context(db)
    prompt = (
        "Review my current portfolio and provide:\n"
        "1. Overall assessment (1-2 sentences)\n"
        "2. Top risk to watch\n"
        "3. One specific action to consider\n"
        "Be brief and data-driven."
    )
    return await llm_client.chat(prompt, context=ctx, model=model)


async def analyze_signal(
    ticker: str,
    db: AsyncSession,
    model: str = llm_client.DEFAULT_MODEL,
) -> str:
    """Explain the latest signal for a ticker."""
    ctx = await context_builder.build_ticker_context(ticker, db)
    prompt = (
        f"Explain the current signal for {ticker}. "
        "Include: what the quant factors are saying, "
        "what the risk/reward looks like, and whether you'd act on it now."
    )
    return await llm_client.chat(prompt, context=ctx, model=model)


# ── Training data stats ────────────────────────────────────────────────────────

async def get_training_stats(db: AsyncSession) -> dict:
    total = await db.scalar(select(func.count()).select_from(LlmTrainingSample))
    wins  = await db.scalar(
        select(func.count()).select_from(LlmTrainingSample)
        .where(LlmTrainingSample.was_correct == True)
    )
    high_q = await db.scalar(
        select(func.count()).select_from(LlmTrainingSample)
        .where(LlmTrainingSample.quality >= 0.7)
    )
    result = await db.execute(
        select(LlmTrainingSample).order_by(desc(LlmTrainingSample.created_at)).limit(3)
    )
    recent = [
        {"ticker": s.ticker, "source": s.source, "quality": round(s.quality, 2)}
        for s in result.scalars().all()
    ]
    return {
        "total_samples": total or 0,
        "win_samples":   wins or 0,
        "high_quality":  high_q or 0,
        "recent":        recent,
        "ready_to_train": (total or 0) >= 50,
    }
