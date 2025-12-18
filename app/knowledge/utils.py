from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def flatten_json_to_text(obj: Any) -> str:
    """
    V1: transforma JSON arbitrário em texto para busca simples.
    - Inclui chaves e valores
    - Mantém strings, números, booleanos
    """
    parts: list[str] = []

    def walk(x: Any, prefix: str = ""):
        if x is None:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k)
                if prefix:
                    parts.append(f"{prefix}.{key}")
                    walk(v, f"{prefix}.{key}")
                else:
                    parts.append(key)
                    walk(v, key)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, prefix)
        elif isinstance(x, (str, int, float, bool)):
            parts.append(str(x))
        else:
            parts.append(str(x))

    walk(obj)
    # limpa e junta
    text = " ".join(p.strip() for p in parts if p and str(p).strip())
    # reduz espaços repetidos
    return " ".join(text.split())

def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)