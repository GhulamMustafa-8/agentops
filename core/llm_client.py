"""
llm_client.py
--------------
Thin wrapper around free/zero-cost LLM backends.

Design goals (per Project Constitution, Principle #2 - Zero-cost by default):
  - No paid API dependency required.
  - Two supported backends, both free:
      1. "ollama"  — fully local, no internet needed after model pull,
                     but requires downloading a multi-GB model first.
      2. "groq"    — free-tier hosted API (console.groq.com), no local
                     download at all — instant to use, but does need
                     internet + a free API key.
  - Switching backends is one env var (LLM_BACKEND); agents/callers never
    know or care which one is active.
"""

import os
import time
import requests
from typing import Optional


class LLMClientError(Exception):
    """Raised when the LLM backend fails to respond or returns an error."""
    pass


class LLMClient:
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        backend: Optional[str] = None,
        timeout: int = 60,
    ):
        # Defaults are read from env vars so the whole system stays
        # configurable without code changes (12-factor style).
        self.backend = backend or os.getenv("LLM_BACKEND", "ollama")
        self.timeout = timeout

        if self.backend == "groq":
            self.model = model or os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
            self.base_url = base_url or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
            self.api_key = os.getenv("GROQ_API_KEY")
        else:
            self.model = model or os.getenv("LLM_MODEL", "llama3.2")
            self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.api_key = None

    def generate(self, prompt: str) -> dict:
        """
        Send a prompt to the configured LLM backend and return a normalized
        result dict:
            {
                "text": str,
                "duration_ms": int,
                "model": str,
            }
        Raises LLMClientError on any failure (connection, timeout, bad response),
        so callers (BaseAgent) can catch it and log a failed run instead of crashing.
        """
        start = time.time()

        if self.backend == "ollama":
            text = self._call_ollama(prompt)
        elif self.backend == "groq":
            text = self._call_groq(prompt)
        else:
            raise LLMClientError(f"Unsupported LLM_BACKEND: {self.backend}")

        duration_ms = int((time.time() - start) * 1000)

        return {
            "text": text,
            "duration_ms": duration_ms,
            "model": self.model,
        }

    def _call_ollama(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise LLMClientError(
                f"Could not connect to Ollama at {self.base_url}. "
                f"Is 'ollama serve' running and is the model pulled "
                f"(try: ollama pull {self.model})? Original error: {e}"
            )
        except requests.exceptions.Timeout as e:
            raise LLMClientError(f"Ollama request timed out after {self.timeout}s: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMClientError(f"Ollama returned an HTTP error: {e}")

        try:
            data = resp.json()
            return data.get("response", "").strip()
        except ValueError as e:
            raise LLMClientError(f"Ollama returned invalid JSON: {e}")

    def _call_groq(self, prompt: str) -> str:
        if not self.api_key:
            raise LLMClientError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
                "and set it as an environment variable before starting the server."
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise LLMClientError(f"Could not connect to Groq at {self.base_url}: {e}")
        except requests.exceptions.Timeout as e:
            raise LLMClientError(f"Groq request timed out after {self.timeout}s: {e}")
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise LLMClientError(f"Groq returned an HTTP error: {e}. {detail}")

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError) as e:
            raise LLMClientError(f"Groq returned an unexpected response shape: {e}")
