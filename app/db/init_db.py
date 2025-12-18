from sqlalchemy import text
from app.db.session import engine
from app.db.models import Base

def init_db():
    # pgvector extension (disponível no container pgvector/pgvector)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

    # cria tabelas (MVP sem migrations)
    Base.metadata.create_all(bind=engine)