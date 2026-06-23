"""
AI Advisor API endpoints.

POST /api/v1/advisor/chat          — send a message, get a reply
GET  /api/v1/advisor/status        — Ollama availability + model list
POST /api/v1/advisor/analyze       — one-shot portfolio or ticker analysis
GET  /api/v1/advisor/training      — training dataset stats
GET  /api/v1/advisor/training/export — download training data as JSONL
POST /api/v1/advisor/pull          — pull an Ollama model
"""
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.db.session import get_db
from app.services.advisor import llm_signal
from app.models.advisor import LlmTrainingSample

router = APIRouter(prefix="/advisor", tags=["advisor"])


class PullRequest(BaseModel):
    model: str = llm_signal.DEFAULT_MODEL


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """Check if Ollama is running and which models are available."""
    available = await llm_signal.is_available()
    models: list[str] = []
    if available:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{llm_signal.OLLAMA_BASE}/api/tags")
                models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
    return {
        "ollama_running": available,
        "models": models,
        "default_model": llm_signal.DEFAULT_MODEL,
        "setup_url": "https://ollama.com/download",
        "recommended_model": "llama3.2:3b",
        "pull_command": "ollama pull llama3.2:3b",
    }


@router.get("/training")
async def get_training_stats(db: AsyncSession = Depends(get_db)):
    """Return training dataset statistics."""
    total   = await db.scalar(select(func.count()).select_from(LlmTrainingSample))
    wins    = await db.scalar(
        select(func.count()).select_from(LlmTrainingSample)
        .where(LlmTrainingSample.was_correct == True)
    )
    high_q  = await db.scalar(
        select(func.count()).select_from(LlmTrainingSample)
        .where(LlmTrainingSample.quality >= 0.7)
    )
    result  = await db.execute(
        select(LlmTrainingSample).order_by(desc(LlmTrainingSample.created_at)).limit(3)
    )
    recent  = [
        {"ticker": s.ticker, "source": s.source, "quality": round(s.quality, 2)}
        for s in result.scalars().all()
    ]
    return {
        "total_samples":  total or 0,
        "win_samples":    wins or 0,
        "high_quality":   high_q or 0,
        "recent":         recent,
        "ready_to_train": (total or 0) >= 50,
    }


@router.get("/training/export")
async def export_training_data(
    min_quality: float = 0.4,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
):
    """Export training data as JSONL for use with finetune_llm.py."""
    result = await db.execute(
        select(LlmTrainingSample)
        .where(LlmTrainingSample.quality >= min_quality)
        .order_by(LlmTrainingSample.quality.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    def generate():
        for row in rows:
            yield json.dumps({"instruction": row.instruction, "response": row.response}) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=blackbox_training_data.jsonl"},
    )


@router.post("/pull")
async def pull_model(req: PullRequest):
    """Initiate Ollama model pull."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{llm_signal.OLLAMA_BASE}/api/pull",
                json={"name": req.model, "stream": False},
                timeout=30,
            )
            r.raise_for_status()
            return {"status": "pulling", "model": req.model}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
