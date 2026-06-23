"""
ORM models for the AI advisor and LLM training pipeline.

LlmTrainingSample stores every (instruction, response) pair collected
from trade outcomes and market events. These accumulate in SQLite and
are exported by scripts/finetune_llm.py when the user runs fine-tuning.

AdvisorConversation stores persistent chat history per session.
"""
from datetime import datetime, timezone
from sqlalchemy import String, Float, Text, Boolean, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class LlmTrainingSample(Base):
    """
    One instruction-following training example derived from a real trade outcome.

    instruction: market context at signal time (regime, scores, price action)
    response:    what the optimal decision was (buy/sell/hold + reasoning)
    quality:     0.0-1.0 score used to filter low-quality samples during training
    source:      where this sample came from (trade_outcome | manual | synthetic)
    """
    __tablename__ = "llm_training_sample"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    instruction: Mapped[str]      = mapped_column(Text, nullable=False)
    response:    Mapped[str]      = mapped_column(Text, nullable=False)
    ticker:      Mapped[str]      = mapped_column(String(16), nullable=True)
    quality:     Mapped[float]    = mapped_column(Float, default=0.5)
    was_correct: Mapped[bool]     = mapped_column(Boolean, nullable=True)
    pnl_pct:     Mapped[float]    = mapped_column(Float, nullable=True)
    source:      Mapped[str]      = mapped_column(String(32), default="trade_outcome")
    metadata_:   Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    created_at:  Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class AdvisorConversation(Base):
    """
    Persists chat sessions so the advisor remembers context across page refreshes.
    """
    __tablename__ = "advisor_conversation"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str]      = mapped_column(String(64), index=True)
    role:       Mapped[str]      = mapped_column(String(16))   # user | assistant | system
    content:    Mapped[str]      = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
