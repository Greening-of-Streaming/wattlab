"""
ollama_api.py — the ONE place that knows where the local Ollama lives (CR-031 §3).

`OLLAMA_HOST` (Ollama's own env convention) wins, so a container can point OWL
at an `ollama` sidecar (`OLLAMA_HOST=http://ollama:11434`). Default is the
loopback daemon GoS1/GoS2 have always used. Remote hosts (CR-085) keep passing
their own tunnel URL explicitly; this is only the local default.
"""
import json
import os
import urllib.request

_DEFAULT = "http://localhost:11434"


def base_url() -> str:
    raw = (os.environ.get("OLLAMA_HOST") or _DEFAULT).strip().rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    # A server-side bind address ("0.0.0.0:11434") is not a client address.
    return raw.replace("://0.0.0.0", "://localhost")


def url(path: str) -> str:
    return f"{base_url()}/{path.lstrip('/')}"


def get_json(path: str, timeout: float = 5) -> dict:
    with urllib.request.urlopen(url(path), timeout=timeout) as r:
        return json.loads(r.read())
