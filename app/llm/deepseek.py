import os
import requests


class DeepSeekClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))

        if not self.api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY in environment")

    def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 800) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        r = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"DeepSeek API error {r.status_code}: {r.text}")

        data = r.json()
        return data["choices"][0]["message"]["content"]