from fastapi import FastAPI

from app.db.session import engine
from app.db.models import Base

from app.api.tasks import router as tasks_router
from app.api.radar import router as radar_router

app = FastAPI(title="Personal Assistant")

@app.on_event("startup")
def startup():
    # Cria as tabelas no SQLite (DEV).
    # Observação: se você mudar schema depois, pode precisar apagar data/app.db
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(tasks_router)
app.include_router(radar_router)