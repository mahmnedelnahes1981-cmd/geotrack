"""OpenAI-compatible chat client (Ollama locally, or any external API).

Temperature is pinned to 0 for reproducible normalization. Raw responses are
always returned so callers can persist them for audit.
"""

import httpx


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.base_url}/chat/completions"
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            if resp.status_code == 400:  # server may not support response_format -> retry without
                payload.pop("response_format")
                resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {getattr(resp, 'text', '')[:500]!r}") from exc
        return content, data
