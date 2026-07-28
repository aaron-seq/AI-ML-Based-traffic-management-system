"""Async persistence layer.

Previously every observation lived in memory and vanished on restart, so the
analytics and forecasting endpoints could only ever describe the current
process. This module gives the system durable history with SQLite by default
(zero setup) and any SQLAlchemy-supported database via ``TRAFFIC_DATABASE_URL``.

Persistence is optional: when it is disabled or the database is unreachable the
application still runs, it just loses history across restarts.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Float, Integer, String, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, DateTime

from .config import settings
from .logger import get_application_logger

logger = get_application_logger("database")


class Base(DeclarativeBase):
    """Declarative base for every persisted table."""


class DetectionRecord(Base):
    """One completed detection run, flattened for querying."""

    __tablename__ = "detection_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detection_id: Mapped[str] = mapped_column(String(64), index=True)
    intersection_id: Mapped[str] = mapped_column(String(64), index=True, default="main_intersection")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total_vehicles: Mapped[int] = mapped_column(Integer, default=0)
    passenger_car_units: Mapped[float] = mapped_column(Float, default=0.0)
    pedestrian_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_time: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="image")
    has_emergency: Mapped[bool] = mapped_column(default=False)
    lane_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CycleRecord(Base):
    """One completed signal cycle, used to reconstruct delay and impact."""

    __tablename__ = "cycle_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[str] = mapped_column(String(64), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cycle_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    vehicles_served: Mapped[int] = mapped_column(Integer, default=0)
    average_wait_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    adaptive_mode: Mapped[bool] = mapped_column(default=True)


class EventRecord(Base):
    """Notable events: emergency pre-emptions, pedestrian requests, faults."""

    __tablename__ = "event_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[str] = mapped_column(String(64), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Database:
    """Owns the engine and session factory, and degrades gracefully."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def connect(self) -> None:
        """Create the engine and schema. Failures disable persistence, not the app."""
        if not settings.persistence_enabled:
            logger.info("Persistence disabled by configuration")
            return

        try:
            self._ensure_sqlite_directory(settings.database_url)
            self._engine = create_async_engine(
                settings.database_url,
                echo=settings.database_echo,
                future=True,
                pool_pre_ping=True,
            )
            async with self._engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
            self._available = True
            logger.info("Persistence ready (%s)", self._safe_url(settings.database_url))

            await self.prune_old_records()
        except (SQLAlchemyError, OSError, ImportError) as error:
            # ImportError covers a database URL whose driver is not installed
            # (e.g. postgresql+asyncpg without asyncpg): still a configuration
            # problem, still no reason to take the signal controller down.
            logger.warning("Persistence unavailable, continuing in memory-only mode: %s", error)
            self._available = False

    @staticmethod
    def _ensure_sqlite_directory(url: str) -> None:
        """Create the parent directory for a file-backed SQLite database."""
        if not url.startswith("sqlite"):
            return
        _, _, path_part = url.partition(":///")
        if not path_part or path_part.startswith(":memory:"):
            return
        Path(path_part).expanduser().parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_url(url: str) -> str:
        """Strip credentials so the URL is safe to log."""
        if "@" not in url:
            return url
        scheme, _, remainder = url.partition("://")
        _, _, host = remainder.rpartition("@")
        return f"{scheme}://***@{host}"

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession | None]:
        """Yield a session, or ``None`` when persistence is unavailable.

        Callers treat ``None`` as "skip persistence" so no call site needs to
        branch on configuration.
        """
        if not self._available or self._sessionmaker is None:
            yield None
            return

        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except SQLAlchemyError as error:
                await session.rollback()
                logger.error("Database transaction failed: %s", error)

    async def prune_old_records(self) -> int:
        """Delete records older than the retention window; returns rows removed."""
        if not self._available:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
        removed = 0
        async with self.session() as session:
            if session is None:
                return 0
            for table in (DetectionRecord, CycleRecord, EventRecord):
                result = await session.execute(delete(table).where(table.recorded_at < cutoff))
                # execute() is typed as returning Result, but a DELETE always
                # yields a CursorResult, which is what carries rowcount.
                removed += cast("CursorResult[Any]", result).rowcount or 0

        if removed:
            logger.info("Pruned %d records older than %d days", removed, settings.retention_days)
        return removed

    async def recent_detections(
        self,
        intersection_id: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[DetectionRecord]:
        """Most recent detection records, newest first."""
        async with self.session() as session:
            if session is None:
                return []
            statement = select(DetectionRecord).order_by(DetectionRecord.recorded_at.desc()).limit(limit)
            if intersection_id:
                statement = statement.where(DetectionRecord.intersection_id == intersection_id)
            if since:
                statement = statement.where(DetectionRecord.recorded_at >= since)
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def disconnect(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
        self._available = False


#: Application-wide database handle.
database = Database()
