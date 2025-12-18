# app/db/models.py
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    Text,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# pgvector é opcional: se não tiver instalado, o app ainda sobe.
try:
    from pgvector.sqlalchemy import Vector  # type: ignore
except Exception:  # pragma: no cover
    Vector = None  # type: ignore


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# -------------------------
# TASKS
# -------------------------

class Task(Base, TimestampMixin):
    """
    Tabela: tasks

    Observação:
    - 'kind' = 'one_off' ou 'recurring'
    - 'is_done' aqui é útil principalmente para one_off.
      Para recurring, o done por ocorrência fica em task_completions.
    """
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")

    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    kind: Mapped[str] = mapped_column(String, nullable=False, index=True, default="one_off")

    # one-off
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    # recurring
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    rrule: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # done flag (principalmente p/ one_off)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    completions: Mapped[List["TaskCompletion"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TaskCompletion(Base):
    """
    Tabela: task_completions

    Guarda apenas ocorrências concluídas (recorrentes) ou eventos de conclusão (caso queira).
    O teu erro atual é que o endpoint está inserindo sem 'user_id' (NOT NULL).
    """
    __tablename__ = "task_completions"
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", "occurrence_date", name="uq_task_occurrence"),
        Index("ix_task_completions_user_id", "user_id"),
        Index("ix_task_completions_task_id", "task_id"),
        Index("ix_task_completions_occurrence_date", "occurrence_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped["Task"] = relationship(back_populates="completions")


# -------------------------
# RADAR
# -------------------------

class RadarItem(Base, TimestampMixin):
    """
    Tabela: radar_items
    """
    __tablename__ = "radar_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")

    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)


# Alias de compatibilidade: se algum router ainda faz `from app.db.models import Radar`
Radar = RadarItem


# -------------------------
# KNOWLEDGE (RAG)
# -------------------------

class KnowledgeItem(Base, TimestampMixin):
    """
    Tabela: knowledge_items (um arquivo)
    """
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")

    source: Mapped[str] = mapped_column(String, nullable=False, default="localfs")  # localfs | gdrive (futuro)

    file_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    folder_date: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeChunk(Base, TimestampMixin):
    """
    Tabela: knowledge_chunks (trechos + embedding)
    """
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_user_id", "user_id"),
        Index("ix_knowledge_chunks_item_id", "item_id"),
        Index("ix_knowledge_chunks_text_hash", "text_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True, default="default")

    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    embedding_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # embedding (pgvector). Se pgvector não estiver disponível, fica como NULL (sem coluna de vetor).
    if Vector is not None:
        embedding: Mapped[Optional[object]] = mapped_column(Vector(), nullable=True)  # Vector() sem dimensão fixa
    else:
        embedding = mapped_column(Text, nullable=True)  # fallback (não ideal, mas mantém o app subindo)

    item: Mapped["KnowledgeItem"] = relationship(back_populates="chunks")


__all__ = [
    "Base",
    "Task",
    "TaskCompletion",
    "RadarItem",
    "Radar",
    "KnowledgeItem",
    "KnowledgeChunk",
]