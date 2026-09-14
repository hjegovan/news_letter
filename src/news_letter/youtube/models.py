# src/news_letter/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..utils.enums import BackfillStatus, ProcessingStatus


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint(
            "platform_channel_id",
            name="uq_channel_platform_channel_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    platform_channel_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    backfill_status: Mapped[BackfillStatus] = mapped_column(
        Enum(BackfillStatus),
        nullable=False,
        default=BackfillStatus.NOT_STARTED,
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    videos: Mapped[list[Video]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint(
            "platform_video_id",
            name="uq_video_platform_video_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    platform_video_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    transcript_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )

    ai_processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    channel: Mapped[Channel] = relationship(
        back_populates="videos",
    )
