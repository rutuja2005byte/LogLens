"""Minimal async client for the Ollama chat API."""
import httpx

from . import config


async def chat(system: str, user: str) -> str:
    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
        resp = await client.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={
                "model": config.OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return (resp.json().get("message") or {}).get("content") or "No answer returned"
