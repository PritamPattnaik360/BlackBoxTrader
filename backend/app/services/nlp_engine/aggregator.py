import math
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from app.config import settings
from app.services.nlp_engine.sentiment import score_texts, label_to_score
from app.services.nlp_engine.news_fetcher import fetch_news

logger = logging.getLogger(__name__)

HALF_LIFE_HOURS = 4.0


@dataclass
class CompositeSignal:
    ticker: str
    composite_score: float       # -1.0 to 1.0
    confidence: float            # 0.0 to 1.0
    direction: str               # BUY | SELL | HOLD
    source_count: int
    news_score: float | None
    reddit_score: float | None   # always None (Reddit disabled)
    raw_headlines: list[dict]
    created_at: datetime


def _recency_weight(published_at: str | float) -> float:
    try:
        if isinstance(published_at, float):
            pub_ts = datetime.fromtimestamp(published_at, tz=timezone.utc)
        else:
            pub_ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        hours_old = (datetime.now(timezone.utc) - pub_ts).total_seconds() / 3600
        return math.exp(-hours_old / HALF_LIFE_HOURS)
    except Exception:
        return 0.5


async def generate_signal(ticker: str) -> CompositeSignal:
    news_items = await fetch_news(ticker)

    texts  = [item["title"] for item in news_items if item.get("title")]
    scored = score_texts(texts)

    def weighted_mean(items: list[dict], item_scores: list[dict]) -> float | None:
        if not items:
            return None
        total_w, total_s = 0.0, 0.0
        for item, result in zip(items, item_scores):
            w = _recency_weight(item.get("published_at", ""))
            s = label_to_score(result["label"], result["score"])
            total_w += w
            total_s += w * s
        return total_s / total_w if total_w > 0 else 0.0

    ns        = weighted_mean(news_items, scored)
    composite = ns if ns is not None else 0.0
    confidence = min(len(news_items) / 10.0, 1.0)

    if composite >= settings.buy_signal_threshold:
        direction = "BUY"
    elif composite <= settings.sell_signal_threshold:
        direction = "SELL"
    else:
        direction = "HOLD"

    raw = [
        {"title": item["title"], "source": item["source"], "score": res["label"]}
        for item, res in zip(news_items[:5], scored[:5])
    ]

    return CompositeSignal(
        ticker=ticker,
        composite_score=round(composite, 4),
        confidence=round(confidence, 4),
        direction=direction,
        source_count=len(news_items),
        news_score=round(ns, 4) if ns is not None else None,
        reddit_score=None,
        raw_headlines=raw,
        created_at=datetime.now(timezone.utc),
    )
