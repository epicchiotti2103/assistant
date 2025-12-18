import os
import requests
from typing import List


class OpenAIEmbeddingsClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small").strip()
        self.dim = int(os.getenv("OPENAI_EMBED_DIM", "1536"))
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY não definido no .env")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Faz embeddings em lote.
        Retorna uma lista de vetores (mesmo tamanho de `texts`).
        """
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": texts,
        }

        # dimensions é suportado nos modelos novos; se não suportar, a API retorna erro.
        # Mantemos porque você já definiu OPENAI_EMBED_DIM.
        payload["dimensions"] = self.dim

        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"OpenAI embeddings error {r.status_code}: {r.text}")

        data = r.json()
        # mantém ordem original
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        return vectors