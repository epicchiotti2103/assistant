from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Radar

router = APIRouter(prefix="/radar", tags=["radar"])


class RadarCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: str | None = None
    priority: int = Field(default=3, ge=1, le=5)


class RadarOut(BaseModel):
    id: int
    title: str
    notes: str | None
    priority: int


@router.get("", response_model=list[RadarOut])
def list_radar(db: Session = Depends(get_db)):
    rows = db.query(Radar).order_by(Radar.priority.asc(), Radar.id.desc()).all()
    return [RadarOut(id=r.id, title=r.title, notes=r.notes, priority=r.priority) for r in rows]


@router.post("", response_model=dict)
def create_radar(payload: RadarCreate, db: Session = Depends(get_db)):
    item = Radar(title=payload.title, notes=payload.notes, priority=payload.priority)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"ok": True, "id": item.id}