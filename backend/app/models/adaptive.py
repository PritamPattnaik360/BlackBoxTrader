from sqlalchemy import String, Float, Boolean, Integer, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from datetime import datetime
from typing import Any


class SignalOutcome(Base):
    """Records the outcome of every AI-generated signal after the position closes."""
    __tablename__ = "signal_outcome"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    signal_direction: Mapped[str] = mapped_column(String(5), nullable=False)   # BUY | SELL
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reddit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    # pnl_pct > 0 means the trade was profitable (regardless of direction)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)
    was_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    regime_at_entry: Mapped[str] = mapped_column(String(20), default="normal")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AdaptiveParam(Base):
    """Versioned history of every adaptive parameter value by generation."""
    __tablename__ = "adaptive_param"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdaptiveEvent(Base):
    """Human-readable log of every adaptation decision."""
    __tablename__ = "adaptive_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
