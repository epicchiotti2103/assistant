from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Literal, Set, Tuple

from dateutil.rrule import rrulestr
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Task, TaskCompletion

router = APIRouter(prefix="/tasks", tags=["tasks"])

DEFAULT_USER_ID = "default"


def _has_attr(model_cls, name: str) -> bool:
    return hasattr(model_cls, name)


def _apply_user_filter(query, model_cls):
    # Só filtra por user_id se o model tiver o atributo (compat)
    if _has_attr(model_cls, "user_id"):
        return query.filter(model_cls.user_id == DEFAULT_USER_ID)
    return query


def _week_range_seg_dom(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())  # segunda-feira
    end = start + timedelta(days=6)  # domingo
    return start, end


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: Optional[str] = None
    priority: int = Field(default=3, ge=1, le=5)

    # One-off
    due_date: Optional[date] = None

    # Recurring
    rrule: Optional[str] = None  # exemplo: "FREQ=MONTHLY;BYMONTHDAY=13"
    start_date: Optional[date] = None


class TaskOut(BaseModel):
    id: int
    user_id: Optional[str] = None
    title: str
    notes: Optional[str] = None
    kind: Literal["one_off", "recurring"]
    date: date
    rrule: Optional[str] = None
    is_done: bool
    priority: int


class OccurrenceDoneIn(BaseModel):
    occurrence_date: date


@router.post("", response_model=dict)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """
    Cria uma tarefa.
    - Se payload.rrule existir => tarefa recorrente (kind=recurring, start_date obrigatório)
    - Caso contrário => tarefa one-off (kind=one_off, due_date)
    """
    is_recurring = bool(payload.rrule)
    kind = "recurring" if is_recurring else "one_off"

    if is_recurring:
        start_date = payload.start_date or date.today()
        due_date = None
        rrule = payload.rrule
        if not rrule:
            raise HTTPException(status_code=400, detail="rrule é obrigatório para tarefas recorrentes")
    else:
        due_date = payload.due_date or payload.start_date or date.today()
        start_date = None
        rrule = None

    kwargs = dict(
        title=payload.title,
        notes=payload.notes,
        priority=payload.priority,
        kind=kind,
        due_date=due_date,
        start_date=start_date,
        rrule=rrule,
    )

    # user_id se o model suportar
    if _has_attr(Task, "user_id"):
        kwargs["user_id"] = DEFAULT_USER_ID

    task = Task(**kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"ok": True, "id": task.id}


@router.post("/{task_id}/complete", response_model=dict)
def complete_occurrence(task_id: int, payload: OccurrenceDoneIn, db: Session = Depends(get_db)):
    """
    Marca como concluída uma ocorrência (recorrente) ou a data da one-off.
    Grava em task_completions: (user_id, task_id, occurrence_date)
    """
    q = db.query(Task).filter(Task.id == task_id)
    q = _apply_user_filter(q, Task)
    task = q.first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # normaliza: one-off só permite completar na due_date (se você quiser permitir qualquer data, remove isso)
    if task.rrule is None:
        if not task.due_date:
            raise HTTPException(status_code=400, detail="one_off task sem due_date")
        if payload.occurrence_date != task.due_date:
            raise HTTPException(status_code=400, detail="one_off só pode ser completada na própria due_date")

    qc = db.query(TaskCompletion).filter(
        TaskCompletion.task_id == task_id,
        TaskCompletion.occurrence_date == payload.occurrence_date,
    )
    qc = _apply_user_filter(qc, TaskCompletion)
    existing = qc.first()
    if existing:
        return {"ok": True, "already": True, "task_id": task_id, "occurrence_date": payload.occurrence_date.isoformat()}

    # >>> AQUI ESTÁ A CORREÇÃO DO TEU ERRO:
    # seu banco exige user_id NOT NULL em task_completions
    comp_kwargs = dict(
        task_id=task_id,
        occurrence_date=payload.occurrence_date,
    )
    if _has_attr(TaskCompletion, "user_id"):
        comp_kwargs["user_id"] = DEFAULT_USER_ID
    # se seu model tiver "completed_at", seta (se não, ignora)
    if _has_attr(TaskCompletion, "completed_at"):
        comp_kwargs["completed_at"] = datetime.utcnow()

    comp = TaskCompletion(**comp_kwargs)
    db.add(comp)
    db.commit()
    return {"ok": True, "task_id": task_id, "occurrence_date": payload.occurrence_date.isoformat()}


@router.get("/today", response_model=list[TaskOut])
def tasks_today(
    date_ref: Optional[date] = None,
    hide_done: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    anchor = date_ref or date.today()
    return _window_tasks(anchor, anchor, db, hide_done=hide_done)


@router.get("/week", response_model=list[TaskOut])
def tasks_week(
    date_ref: Optional[date] = None,
    hide_done: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    anchor = date_ref or date.today()
    start, end = _week_range_seg_dom(anchor)
    return _window_tasks(start, end, db, hide_done=hide_done)


@router.get("/next", response_model=list[TaskOut])
def tasks_next(
    days: int = 14,
    date_ref: Optional[date] = None,
    hide_done: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    if days < 1 or days > 365:
        days = 14
    anchor = date_ref or date.today()
    end = anchor + timedelta(days=days - 1)
    return _window_tasks(anchor, end, db, hide_done=hide_done)


def _window_tasks(start: date, end: date, db: Session, hide_done: bool) -> list[TaskOut]:
    results: list[TaskOut] = []

    # --- completions no intervalo ---
    qc = db.query(TaskCompletion).filter(
        TaskCompletion.occurrence_date >= start,
        TaskCompletion.occurrence_date <= end,
    )
    qc = _apply_user_filter(qc, TaskCompletion)
    completions = qc.all()
    done_set: Set[Tuple[int, date]] = {(c.task_id, c.occurrence_date) for c in completions}

    # --- one-off ---
    qo = db.query(Task).filter(
        Task.rrule.is_(None),
        Task.due_date.is_not(None),
        Task.due_date >= start,
        Task.due_date <= end,
    )
    qo = _apply_user_filter(qo, Task)
    one_off = qo.all()

    for t in one_off:
        is_done = (t.id, t.due_date) in done_set
        if hide_done and is_done:
            continue
        results.append(
            TaskOut(
                id=t.id,
                user_id=getattr(t, "user_id", None),
                title=t.title,
                notes=t.notes,
                kind="one_off",
                date=t.due_date,
                rrule=None,
                is_done=is_done,
                priority=t.priority,
            )
        )

    # --- recurring ---
    qr = db.query(Task).filter(
        Task.rrule.is_not(None),
        Task.start_date.is_not(None),
        Task.start_date <= end,
    )
    qr = _apply_user_filter(qr, Task)
    recurring = qr.all()

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
            for dt in occ:
                od = dt.date()
                is_done = (t.id, od) in done_set
                if hide_done and is_done:
                    continue
                results.append(
                    TaskOut(
                        id=t.id,
                        user_id=getattr(t, "user_id", None),
                        title=t.title,
                        notes=t.notes,
                        kind="recurring",
                        date=od,
                        rrule=t.rrule,
                        is_done=is_done,
                        priority=t.priority,
                    )
                )
        except Exception:
            # rrule inválida não derruba o endpoint
            continue

    # ordenação
    results.sort(key=lambda x: (x.date, x.priority, (x.title or "").lower()))
    return results