from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import KnowledgeItem
from app.llm.deepseek import DeepSeekClient

router = APIRouter(prefix="/chat", tags=["chat"])
DEFAULT_USER_ID = "default"


class ChatPreviewIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    use_context: bool = True
    limit: int = 5


class SuggestedMemory(BaseModel):
    id: int
    file_path: str
    folder_date: str | None
    snippet: str


class ChatPreviewOut(BaseModel):
    use_context: bool
    suggested: list[SuggestedMemory]
    context_preview: str


class ChatRespondIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    use_context: bool = True
    approved_ids: list[int] = []
    temperature: float = 0.2
    max_tokens: int = 900


class ChatRespondOut(BaseModel):
    answer: str
    used_context: bool
    used_ids: list[int]


def _tokenize(q: str) -> list[str]:
    import re

    q_low = (q or "").lower()
    tokens = re.findall(r"[a-z0-9_]+", q_low)

    stop = {"como", "resolvo", "erro", "no", "na", "pro", "para", "de", "do", "da", "um", "uma", "que", "o", "a", "e"}
    tokens = [t for t in tokens if len(t) >= 3 and t not in stop]

    # boosts úteis pro seu caso
    if "gcs" in q_low or "bucket" in q_low or "storage" in q_low:
        tokens += ["bucket", "gcs", "iam", "permiss", "writer", "storage"]
    if "403" in q_low:
        tokens += ["forbidden", "permission", "permiss", "iam", "writer"]

    # remove duplicados mantendo ordem
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)

    return out[:10]


def _search_memory(db: Session, q: str, limit: int) -> list[SuggestedMemory]:
    tokens = _tokenize(q)
    if not tokens:
        return []

    from sqlalchemy import or_

    clauses = [KnowledgeItem.content_text.ilike(f"%{t}%") for t in tokens]
    rows = (
        db.query(KnowledgeItem)
        .filter(KnowledgeItem.user_id == DEFAULT_USER_ID)
        .filter(or_(*clauses))
        .order_by(KnowledgeItem.updated_at.desc())
        .limit(limit)
        .all()
    )

    out: list[SuggestedMemory] = []
    for r in rows:
        text = r.content_text or ""
        snippet = text[:220]
        for t in tokens:
            idx = text.lower().find(t)
            if idx != -1:
                start = max(0, idx - 80)
                end = min(len(text), idx + 140)
                snippet = text[start:end]
                break

        out.append(
            SuggestedMemory(
                id=r.id,
                file_path=r.file_path,
                folder_date=r.folder_date,
                snippet=snippet,
            )
        )
    return out

def _build_context_block(items: list[KnowledgeItem], max_chars: int = 6000) -> str:
    chunks = []
    total = 0
    for it in items:
        header = f"[MEMORY id={it.id} file={it.file_path} folder={it.folder_date}]\n"
        body = (it.content_text or "")[:2000].strip()
        piece = header + body + "\n"
        if total + len(piece) > max_chars:
            break
        chunks.append(piece)
        total += len(piece)
    return "\n---\n".join(chunks).strip()


@router.post("/preview", response_model=ChatPreviewOut)
def preview(payload: ChatPreviewIn, db: Session = Depends(get_db)):
    suggested: list[SuggestedMemory] = []
    context_preview = ""

    if payload.use_context:
        suggested = _search_memory(db, payload.message, max(1, min(payload.limit, 10)))
        ids = [s.id for s in suggested]
        if ids:
            items = (
                db.query(KnowledgeItem)
                .filter(KnowledgeItem.user_id == DEFAULT_USER_ID, KnowledgeItem.id.in_(ids))
                .all()
            )
            context_preview = _build_context_block(items)

    return ChatPreviewOut(use_context=payload.use_context, suggested=suggested, context_preview=context_preview)


@router.post("/respond", response_model=ChatRespondOut)
def respond(payload: ChatRespondIn, db: Session = Depends(get_db)):
    used_ids: list[int] = []
    context_block = ""

    if payload.use_context:
        if payload.approved_ids:
            used_ids = payload.approved_ids
        else:
            suggested = _search_memory(db, payload.message, 5)
            used_ids = [s.id for s in suggested]

        if used_ids:
            items = (
                db.query(KnowledgeItem)
                .filter(KnowledgeItem.user_id == DEFAULT_USER_ID, KnowledgeItem.id.in_(used_ids))
                .all()
            )
            context_block = _build_context_block(items)

    system = (
        "Você é um assistente pessoal. Responda de forma direta e prática.\n"
        "Se houver CONTEXTO (memórias), use-o para adaptar a resposta ao histórico do usuário.\n"
        "Se o contexto não tiver relação, ignore e responda normalmente.\n"
        "Não invente fatos."
    )

    user_msg = payload.message
    if context_block:
        user_msg = f"{payload.message}\n\nCONTEXTO (memórias recuperadas):\n{context_block}"

    try:
        client = DeepSeekClient()
        answer = client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return ChatRespondOut(answer=answer, used_context=bool(context_block), used_ids=used_ids)