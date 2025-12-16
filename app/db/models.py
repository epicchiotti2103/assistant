from datetime import datetime, date

from sqlalchemy import String, Integer, Date, DateTime, Boolean, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(240))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 1 (alta) .. 5 (baixa)
    priority: Mapped[int] = mapped_column(Integer, default=3)

    # Tarefa “uma vez” (com data)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # Recorrência (RRULE do dateutil, ex: FREQ=MONTHLY;BYMONTHDAY=13)
    rrule: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    is_done: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RadarItem(Base):
    __tablename__ = "radar_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(240))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 1 (alta) .. 5 (baixa)
    priority: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)