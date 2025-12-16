import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _default_db_url() -> str:
    # Dentro do container, persistimos o sqlite em /app/data/app.db
    # (docker-compose mapeia ./data -> /app/data)
    return "sqlite:////app/data/app.db"

DB_URL = os.getenv("DB_URL", _default_db_url())

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()