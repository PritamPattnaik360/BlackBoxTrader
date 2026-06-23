"""
Training data collector for the local LLM.

Every closed trade is converted into an instruction-following example and
stored in `llm_training_sample` in the same SQLite database.
After enough samples accumulate, `scripts/finetune_llm.py` reads them and
fine-tunes a local model via LoRA.

Data format (instruction-tuning style):
  instruction: market context at signal time
  response:    what the optimal decision was + outcome
"""
import logging
from app.db.session import AsyncSessionLocal
from app.models.advisor import LlmTrainingSample

logger = logging.getLogger(__name__)


async def save_training_sample(
    *,
    ticker: str,
    direction: str,
    composite_score: float,
    news_score: float | None,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    was_correct: bool,
    regime: str = "normal",
    extra_scores: dict | None = None,
) -> None:
    """
    Build and persist one instruction-following training example from a
    closed trade outcome. Called automatically after every position close.
    """
    scores_str = f"combined={composite_score:+.3f}"
    if news_score is not None:
        scores_str += f", NLP={news_score:+.3f}"
    if extra_scores:
        for k, v in extra_scores.items():
            scores_str += f", {k}={v:+.3f}"

    instruction = (
        f"You are analyzing a {direction} trade signal for {ticker}.\n"
        f"Signal scores: {scores_str}\n"
        f"Market regime: {regime}\n"
        f"Entry price: ${entry_price:.2f}\n"
        f"Should this {direction} trade on {ticker} be executed?"
    )

    pnl_str = f"{pnl_pct * 100:+.2f}%"
    if was_correct:
        response = (
            f"Yes. This {direction} trade on {ticker} was correct — "
            f"it closed at {pnl_str} PnL. "
            f"The combined signal of {composite_score:+.3f} in a {regime} regime "
            f"correctly predicted the price move. Execute similar setups."
        )
    else:
        response = (
            f"No. This {direction} trade on {ticker} was a mistake — "
            f"it closed at {pnl_str} PnL. "
            f"The signal of {composite_score:+.3f} in a {regime} regime "
            f"was insufficient. Avoid similar setups without stronger confirmation."
        )

    # Higher absolute PnL = more informative sample = higher quality weight
    quality = min(0.3 + abs(pnl_pct) * 10, 1.0)

    async with AsyncSessionLocal() as db:
        db.add(LlmTrainingSample(
            instruction=instruction,
            response=response,
            ticker=ticker,
            quality=quality,
            was_correct=was_correct,
            pnl_pct=pnl_pct,
            source="trade_outcome",
            metadata_={
                "direction": direction,
                "regime": regime,
                "composite_score": composite_score,
                "news_score": news_score,
            },
        ))
        await db.commit()

    logger.debug(f"LLM training sample saved: {ticker} {direction} {pnl_str} correct={was_correct}")
