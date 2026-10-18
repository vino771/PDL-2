"""
ollama_client.py
----------------
Lightweight Ollama HTTP client.

Calls the local Ollama REST API to run inference on qwen2.5:0.5b.
If Ollama is unavailable the caller receives None and falls back to
the deterministic safety controller.
"""
import time
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("OLLAMA")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
OLLAMA_TIMEOUT = 45  # seconds


def _extract_json(text: str) -> Optional[Dict]:
    """Extract the first valid JSON object from a string (handles markdown fences)."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` blocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding any {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def is_ollama_online() -> bool:
    """Check whether Ollama is reachable."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False



def query_ollama(prompt: str, retries: int = 1) -> Optional[Dict[str, Any]]:
    """Call Ollama, parse JSON, and log whether inference succeeded."""

    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 300,
        },
    }

    for attempt in range(retries + 1):
        started = time.perf_counter()

        try:
            logger.info(
                "[OLLAMA] Sending inference request | model=%s | attempt=%d",
                OLLAMA_MODEL,
                attempt + 1,
            )

            resp = requests.post(
                url,
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()

            raw_text = resp.json().get("response", "")
            elapsed = time.perf_counter() - started

            logger.info(
                "[OLLAMA] Response received | model=%s | seconds=%.2f",
                OLLAMA_MODEL,
                elapsed,
            )

            parsed = _extract_json(raw_text)

            if parsed is not None:
                logger.info(
                    "[OLLAMA] JSON parsed successfully | returned_keys=%s",
                    list(parsed.keys()),
                )
                return parsed

            logger.warning(
                "[OLLAMA] Invalid JSON response | attempt=%d | preview=%s",
                attempt + 1,
                raw_text[:200].replace("\n", " "),
            )

        except requests.exceptions.ConnectionError:
            logger.warning(
                "[OLLAMA] Connection failed | URL=%s",
                OLLAMA_BASE_URL,
            )
            return None

        except requests.exceptions.Timeout:
            logger.warning(
                "[OLLAMA] Request timed out after %s seconds",
                OLLAMA_TIMEOUT,
            )
            return None

        except Exception:
            logger.exception("[OLLAMA] Request or response processing failed")

    logger.warning("[OLLAMA] No valid JSON response; caller should use fallback")
    return None
