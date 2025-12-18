from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import KnowledgeItem, KnowledgeChunk

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

DEFAULT_USER_ID = "default"


def _has_attr(model_cls, name: str) -> bool:
    return hasattr(model_cls, name)


def get_knowledge_dir() -> Path:
    return Path(os.getenv("KNOWLEDGE_DIR", "/app/base_conhecimento"))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_json_file(fp: Path) -> Any:
    # Lê como JSON padrão (se der erro, sobe para o caller tratar)
    with fp.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json_compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def flatten_json_to_text(obj: Any) -> str:
    """
    “Achatamento” simples para busca keyword/snippet.
    (Depois você pode trocar por flatten semântico por seções.)
    """
    lines: list[str] = []

    def walk(x: Any, prefix: str = ""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{prefix}{k}: ")
        elif isinstance(x, list):
            for i, v in enumerate(x[:50]):  # corta listas enormes
                walk(v, f"{prefix}[{i}] ")
        else:
            s = "" if x is None else str(x)
            s = s.replace("\n", " ").strip()
            if s:
                lines.append(f"{prefix}{s}")

    walk(obj)
    text = "\n".join(lines)
    # evita payload absurdo
    if len(text) > 200_000:
        text = text[:200_000]
    return text


def chunk_text(text: str, chunk_size: int = 1100, overlap: int = 180) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if chunk_size < 200:
        chunk_size = 200
    if overlap < 0:
        overlap = 0
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)

    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + chunk_size)
        chunk = text[i:j].strip()
        if chunk:
            chunks.append(chunk)
        if j == n:
            break
        i = j - overlap
    return chunks


class SyncError(BaseModel):
    file: str
    error: str


class SyncResult(BaseModel):
    ok: bool = True
    scanned_files: int
    created: int
    updated: int
    unchanged: int
    errors: int
    knowledge_dir: str
    errors_detail: list[SyncError] = Field(default_factory=list)


class KnowledgeOut(BaseModel):
    id: int
    source: str
    folder_date: Optional[str] = None
    file_path: str
    updated_at: datetime


class KnowledgeSearchOut(BaseModel):
    id: int
    folder_date: Optional[str] = None
    file_path: str
    snippet: str


class ChunkRequest(BaseModel):
    item_id: int
    chunk_size: int = 1100
    overlap: int = 180


class EmbedRequest(BaseModel):
    item_id: Optional[int] = None
    model: str = "text-embedding-3-small"
    limit: int = 200
    force: bool = False


class SemanticSearchOut(BaseModel):
    chunk_id: int
    item_id: int
    file_path: str
    folder_date: Optional[str] = None
    score: float
    text: str


def _apply_user_filter(query, model_cls):
    if _has_attr(model_cls, "user_id"):
        return query.filter(model_cls.user_id == DEFAULT_USER_ID)
    return query


@router.post("/sync_local", response_model=SyncResult)
def sync_local(dry_run: bool = False, db: Session = Depends(get_db)):
    base = get_knowledge_dir()
    if not base.exists():
        raise HTTPException(status_code=400, detail=f"KNOWLEDGE_DIR not found: {base}")

    scanned = created = updated = unchanged = errors = 0
    errors_detail: list[SyncError] = []

    for fp in base.rglob("*.json"):
        scanned += 1
        try:
            rel = fp.relative_to(base).as_posix()  # ex: 2025-12-10/file.json
            folder_date = fp.parent.name if fp.parent != base else None

            obj = read_json_file(fp)
            raw = dump_json_compact(obj)
            text = flatten_json_to_text(obj)

            content_hash = sha256_bytes(raw.encode("utf-8"))

            q = db.query(KnowledgeItem).filter(
                KnowledgeItem.source == "localfs",
                KnowledgeItem.file_path == rel,
            )
            q = _apply_user_filter(q, KnowledgeItem)
            existing = q.first()

            # Decide "unchanged"
            if existing:
                if _has_attr(KnowledgeItem, "content_hash"):
                    if getattr(existing, "content_hash", None) == content_hash:
                        unchanged += 1
                        continue
                elif _has_attr(KnowledgeItem, "file_hash"):
                    if getattr(existing, "file_hash", None) == content_hash:
                        unchanged += 1
                        continue
                else:
                    if (existing.content_text or "") == text:
                        unchanged += 1
                        continue

            if dry_run:
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            if existing:
                existing.folder_date = folder_date
                existing.content_text = text
                if _has_attr(KnowledgeItem, "content_hash"):
                    existing.content_hash = content_hash
                if _has_attr(KnowledgeItem, "file_hash"):
                    existing.file_hash = content_hash
                if _has_attr(KnowledgeItem, "raw_json"):
                    existing.raw_json = raw
                if _has_attr(KnowledgeItem, "last_synced_at"):
                    existing.last_synced_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                kwargs = dict(
                    source="localfs",
                    folder_date=folder_date,
                    file_path=rel,
                    content_text=text,
                    updated_at=datetime.utcnow(),
                )
                if _has_attr(KnowledgeItem, "user_id"):
                    kwargs["user_id"] = DEFAULT_USER_ID
                if _has_attr(KnowledgeItem, "content_hash"):
                    kwargs["content_hash"] = content_hash
                if _has_attr(KnowledgeItem, "file_hash"):
                    kwargs["file_hash"] = content_hash
                if _has_attr(KnowledgeItem, "raw_json"):
                    kwargs["raw_json"] = raw
                if _has_attr(KnowledgeItem, "created_at"):
                    kwargs["created_at"] = datetime.utcnow()
                if _has_attr(KnowledgeItem, "last_synced_at"):
                    kwargs["last_synced_at"] = datetime.utcnow()

                item = KnowledgeItem(**kwargs)
                db.add(item)
                created += 1

            db.commit()

        except Exception as e:
            errors += 1
            db.rollback()
            errors_detail.append(SyncError(file=str(fp), error=repr(e)))

    return SyncResult(
        scanned_files=scanned,
        created=created,
        updated=updated,
        unchanged=unchanged,
        errors=errors,
        errors_detail=errors_detail,
        knowledge_dir=str(base),
    )


@router.get("/items", response_model=list[KnowledgeOut])
def list_items(limit: int = 50, db: Session = Depends(get_db)):
    if limit < 1 or limit > 500:
        limit = 50

    q = db.query(KnowledgeItem)
    q = _apply_user_filter(q, KnowledgeItem)
    items = q.order_by(KnowledgeItem.updated_at.desc()).limit(limit).all()

    return [
        KnowledgeOut(
            id=i.id,
            source=i.source,
            folder_date=i.folder_date,
            file_path=i.file_path,
            updated_at=i.updated_at,
        )
        for i in items
    ]


@router.get("/search", response_model=list[KnowledgeSearchOut])
def search(
    q: str = Query(min_length=1),
    limit: int = 10,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 50:
        limit = 10

    like = f"%{q}%"
    qry = db.query(KnowledgeItem).filter(KnowledgeItem.content_text.ilike(like))
    qry = _apply_user_filter(qry, KnowledgeItem)
    rows = qry.order_by(KnowledgeItem.updated_at.desc()).limit(limit).all()

    out: list[KnowledgeSearchOut] = []
    ql = q.lower()
    for r in rows:
        text = r.content_text or ""
        idx = text.lower().find(ql)
        if idx == -1:
            snippet = text[:220]
        else:
            start = max(0, idx - 80)
            end = min(len(text), idx + 140)
            snippet = text[start:end]
        out.append(
            KnowledgeSearchOut(
                id=r.id,
                folder_date=r.folder_date,
                file_path=r.file_path,
                snippet=snippet,
            )
        )
    return out


@router.get("/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    q = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id)
    q = _apply_user_filter(q, KnowledgeItem)
    item = q.first()
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    payload = {
        "id": item.id,
        "source": item.source,
        "folder_date": item.folder_date,
        "file_path": item.file_path,
        "updated_at": item.updated_at.isoformat(),
    }
    if _has_attr(KnowledgeItem, "raw_json"):
        payload["raw_json"] = item.raw_json
    return payload


@router.post("/chunk", response_model=dict)
def make_chunks(req: ChunkRequest, db: Session = Depends(get_db)):
    q = db.query(KnowledgeItem).filter(KnowledgeItem.id == req.item_id)
    q = _apply_user_filter(q, KnowledgeItem)
    item = q.first()
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    chunks = chunk_text(item.content_text or "", chunk_size=req.chunk_size, overlap=req.overlap)

    # apaga chunks antigos do item
    db.query(KnowledgeChunk).filter(KnowledgeChunk.item_id == item.id).delete()
    db.commit()

    # recria
    for idx, txt in enumerate(chunks):
        ck_kwargs = dict(item_id=item.id, chunk_index=idx, text=txt)
        # user_id se existir no model
        if _has_attr(KnowledgeChunk, "user_id"):
            ck_kwargs["user_id"] = getattr(item, "user_id", DEFAULT_USER_ID)
        db.add(KnowledgeChunk(**ck_kwargs))

    db.commit()
    return {"ok": True, "item_id": item.id, "chunks": len(chunks)}


def _openai_embed(texts: list[str], model: str) -> list[list[float]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY não configurada (necessária para /embed e /semantic_search)")

    # endpoint embeddings
    url = "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": model, "input": texts}

    with httpx.Client(timeout=60) as client:
        r = client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Erro embeddings API: {r.status_code} {r.text[:200]}")
        data = r.json()

    # data["data"] é lista na mesma ordem do input
    return [row["embedding"] for row in data["data"]]


@router.post("/embed", response_model=dict)
def embed_chunks(req: EmbedRequest, db: Session = Depends(get_db)):
    limit = req.limit
    if limit < 1 or limit > 2000:
        limit = 200

    q = db.query(KnowledgeChunk)
    if req.item_id is not None:
        q = q.filter(KnowledgeChunk.item_id == req.item_id)

    if not req.force:
        q = q.filter(KnowledgeChunk.embedding.is_(None))

    q = q.order_by(KnowledgeChunk.id.asc()).limit(limit)
    chunks = q.all()

    if not chunks:
        return {"ok": True, "embedded": 0, "model": req.model}

    # batch (OpenAI aceita lista)
    texts = [c.text for c in chunks]
    embeddings = _openai_embed(texts, req.model)

    if len(embeddings) != len(chunks):
        raise HTTPException(status_code=400, detail="Embeddings retornaram tamanho inesperado")

    for c, emb in zip(chunks, embeddings):
        c.embedding = emb
        if _has_attr(KnowledgeChunk, "embedding_model"):
            c.embedding_model = req.model
        if _has_attr(KnowledgeChunk, "updated_at"):
            c.updated_at = datetime.utcnow()

    db.commit()
    return {"ok": True, "embedded": len(chunks), "model": req.model, "item_id": req.item_id}


@router.get("/semantic_search", response_model=list[SemanticSearchOut])
def semantic_search(
    q: str = Query(min_length=1),
    k: int = 5,
    db: Session = Depends(get_db),
):
    if k < 1 or k > 25:
        k = 5

    # embedding da query
    qvec = _openai_embed([q], model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))[0]

    # busca por similaridade (pgvector)
    # score = menor distância => mais similar. Vou converter para "score" invertido simples.
    qry = (
        db.query(KnowledgeChunk, KnowledgeItem)
        .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.item_id)
        .filter(KnowledgeChunk.embedding.is_not(None))
    )
    qry = _apply_user_filter(qry, KnowledgeItem)

    # order by cosine distance
    qry = qry.order_by(KnowledgeChunk.embedding.cosine_distance(qvec)).limit(k)
    rows = qry.all()

    out: list[SemanticSearchOut] = []
    for ch, it in rows:
        dist = float(ch.embedding.cosine_distance(qvec))  # type: ignore
        score = 1.0 / (1.0 + dist)  # só para ficar intuitivo (0..1 aprox)
        out.append(
            SemanticSearchOut(
                chunk_id=ch.id,
                item_id=it.id,
                file_path=it.file_path,
                folder_date=it.folder_date,
                score=score,
                text=ch.text[:1200],
            )
        )
    return out