from sqlalchemy import String, Float, Integer, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from datetime import datetime
from typing import Any


class Signal(Base):
    __tablename__ = "signal"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # BUY | SELL | HOLD
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reddit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_headlines: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
