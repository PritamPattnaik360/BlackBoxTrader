import logging
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)
_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    try:
        from transformers import pipeline as hf_pipeline
        model_path = Path(settings.finbert_model_path)
        source = str(model_path) if model_path.exists() else "ProsusAI/finbert"
        _pipeline = hf_pipeline(
            "text-classification",
            model=source,
            device=-1,  # CPU
            truncation=True,
            max_length=512,
        )
        logger.info(f"FinBERT loaded from {source}")
    except Exception as e:
        logger.error(f"FinBERT load failed: {e} — using dummy scorer")
        _pipeline = None
    return _pipeline


def score_texts(texts: list[str]) -> list[dict]:
    """Return list of {label, score} for each text. label ∈ {positive, neutral, negative}."""
    if not texts:
        return []
    pipe = _load_pipeline()
    if pipe is None:
        return [{"label": "neutral", "score": 0.5} for _ in texts]

    results = []
    batch_size = settings.finbert_batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            out = pipe(batch)
            results.extend(out if isinstance(out[0], dict) else [o[0] for o in out])
        except Exception as e:
            logger.warning(f"FinBERT batch error: {e}")
            results.extend([{"label": "neutral", "score": 0.5}] * len(batch))
    return results


def label_to_score(label: str, confidence: float) -> float:
    """Convert FinBERT label+confidence to a -1..1 float."""
    label = label.lower()
    if label == "positive":
        return confidence
    if label == "negative":
        return -confidence
    return 0.0
