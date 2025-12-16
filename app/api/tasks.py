from datetime import date, datetime, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from dateutil.rrule import rrulestr

from app.db.session import get_db
from app.db.models import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])

DEFAULT_USER_ID = "default"  # V1: depois vira auth/multiusuário


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: Optional[str] = None

    # 1 (alta) .. 5 (baixa)
    priority: int = Field(default=3, ge=1, le=5)

    # UMA VEZ
    due_date: Optional[date] = None

    # RECORRENTE
    rrule: Optional[str] = None  # ex: "FREQ=MONTHLY;BYMONTHDAY=13"
    start_date: Optional[date] = None


class TaskOut(BaseModel):
    id: int
    user_id: str
    title: str
    notes: Optional[str]
    kind: Literal["one_off", "recurring"]
    date: date
    rrule: Optional[str] = None
    is_done: Optional[bool] = None
    priority: int


def week_range_seg_dom(anchor: date) -> tuple[date, date]:
    # Seg=0 ... Dom=6
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    return start, end


@router.post("", response_model=dict)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    # Se tiver rrule => recorrente. Senão => one-off.
    # start_date default: start_date/due_date/hoje (para recorrente)
    start_date = payload.start_date or payload.due_date or date.today()

    task = Task(
        user_id=DEFAULT_USER_ID,
        title=payload.title,
        notes=payload.notes,
        priority=payload.priority,
        due_date=payload.due_date if not payload.rrule else None,
        rrule=payload.rrule,
        start_date=start_date if payload.rrule else None,
        is_done=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"ok": True, "id": task.id}


@router.get("/week", response_model=list[TaskOut])
def tasks_of_week(date_ref: Optional[date] = None, db: Session = Depends(get_db)):
    anchor = date_ref or date.today()
    start, end = week_range_seg_dom(anchor)
    return _window_tasks(start, end, db)


@router.get("/today", response_model=list[TaskOut])
def tasks_today(date_ref: Optional[date] = None, db: Session = Depends(get_db)):
    anchor = date_ref or date.today()
    return _window_tasks(anchor, anchor, db)


@router.get("/next", response_model=list[TaskOut])
def tasks_next(days: int = 14, date_ref: Optional[date] = None, db: Session = Depends(get_db)):
    # limites simples para evitar abusos
    if days < 1 or days > 365:
        days = 14
    anchor = date_ref or date.today()
    end = anchor + timedelta(days=days - 1)
    return _window_tasks(anchor, end, db)


def _window_tasks(start: date, end: date, db: Session) -> list[TaskOut]:
    results: list[TaskOut] = []

    # 1) One-off: due_date dentro da janela
    one_off = (
        db.query(Task)
        .filter(
            Task.user_id == DEFAULT_USER_ID,
            Task.rrule.is_(None),
            Task.due_date.is_not(None),
            Task.due_date >= start,
            Task.due_date <= end,
        )
        .all()
    )
    for t in one_off:
        results.append(
            TaskOut(
                id=t.id,
                user_id=t.user_id,
                title=t.title,
                notes=t.notes,
                kind="one_off",
                date=t.due_date,
                rrule=None,
                is_done=t.is_done,
                priority=t.priority,
            )
        )

    # 2) Recorrentes: gerar ocorrências na janela
    recurring = (
        db.query(Task)
        .filter(
            Task.user_id == DEFAULT_USER_ID,
            Task.rrule.is_not(None),
            Task.start_date.is_not(None),
            Task.start_date <= end,
        )
        .all()
    )

    for t in recurring:
        try:
            rule = rrulestr(
                t.rrule,
                dtstart=datetime.combine(t.start_date, datetime.min.time()),
            )
            occ = rule.between(
                datetime.combine(start, datetime.min.time()),
                datetime.combine(end, datetime.max.time()),
                inc=True,
            )
            for d in occ:
                results.append(
                    TaskOut(
                        id=t.id,
                        user_id=t.user_id,
                        title=t.title,
                        notes=t.notes,
                        kind="recurring",
                        date=d.date(),
                        rrule=t.rrule,
                        is_done=None,  # V1: sem "feito por ocorrência"
                        priority=t.priority,
                    )
                )
        except Exception:
            # V1: se a rrule estiver inválida, ignora
            pass

    # Ordenação: data primeiro, depois prioridade (1 primeiro), depois título
    results.sort(key=lambda x: (x.date, x.priority, x.title.lower()))
    return results