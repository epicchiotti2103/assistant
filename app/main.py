from fastapi import FastAPI

from app.db.session import engine
from app.db.models import Base

from app.api.tasks import router as tasks_router
from app.api.radar import router as radar_router
from app.api.agenda import router as agenda_router
from app.api.knowledge import router as knowledge_router

app = FastAPI(title="Personal Assistant")
from app.db.init_db import init_db

@app.on_event("startup")
def _startup():
    init_db()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(tasks_router)
app.include_router(radar_router)
app.include_router(agenda_router)
app.include_router(knowledge_router)