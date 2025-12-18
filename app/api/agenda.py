from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import RadarItem
from app.api.tasks import tasks_today, tasks_next  # reutiliza a lógica existente

router = APIRouter(prefix="/agenda", tags=["agenda"])

DEFAULT_USER_ID = "default"


@router.get("/overview", response_model=dict)
def overview(days: int = 14, date_ref: Optional[date] = None, db: Session = Depends(get_db)):
    # Reaproveita as funções já prontas
    today_list = tasks_today(date_ref=date_ref, db=db)
    next_list = tasks_next(days=days, date_ref=date_ref, db=db)

    radar_items = (
        db.query(RadarItem)
        .filter(RadarItem.user_id == DEFAULT_USER_ID)
        .order_by(RadarItem.priority.asc(), RadarItem.created_at.desc())
        .all()
    )
    radar = [
        {"id": r.id, "title": r.title, "notes": r.notes, "priority": r.priority}
        for r in radar_items
    ]

    return {
        "date_ref": (date_ref or date.today()).isoformat(),
        "days": days,
        "today": [t.model_dump() for t in today_list],
        "next": [t.model_dump() for t in next_list],
        "radar": radar,
    }