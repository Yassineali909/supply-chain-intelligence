"""Thin Ollama adapter: turns (system, user) into a string response from llama3.2:3b."""
from __future__ import annotations
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"


def ollama_call(system: str, user: str) -> str:
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()["message"]["content"]
