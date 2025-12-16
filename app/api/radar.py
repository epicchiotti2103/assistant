from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import RadarItem

router = APIRouter(prefix="/radar", tags=["radar"])

DEFAULT_USER_ID = "default"  # V1: depois vira auth/multiusuário


class RadarCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: Optional[str] = None
    priority: int = Field(default=3, ge=1, le=5)


class RadarOut(BaseModel):
    id: int
    title: str
    notes: Optional[str]
    priority: int


@router.post("", response_model=dict)
def create_radar(payload: RadarCreate, db: Session = Depends(get_db)):
    item = RadarItem(
        user_id=DEFAULT_USER_ID,
        title=payload.title,
        notes=payload.notes,
        priority=payload.priority,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"ok": True, "id": item.id}


@router.get("", response_model=list[RadarOut])
def list_radar(db: Session = Depends(get_db)):
    items = (
        db.query(RadarItem)
        .filter(RadarItem.user_id == DEFAULT_USER_ID)
        .order_by(RadarItem.priority.asc(), RadarItem.created_at.desc())
        .all()
    )
    return [
        RadarOut(id=i.id, title=i.title, notes=i.notes, priority=i.priority)
        for i in items
    ]