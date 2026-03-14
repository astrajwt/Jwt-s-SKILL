#!/usr/bin/env python3
"""
api_client.py - Claude API wrapper for paper-daily pipeline.

Setup: set ONE of these environment variables:
  PAPER_DAILY_API_KEY   → your Anthropic API key "sk-ant-..." (recommended)
  ANTHROPIC_API_KEY     → same, fallback name

Optional:
  PAPER_DAILY_BASE_URL  → custom API endpoint (default: https://api.anthropic.com)
  PAPER_DAILY_MODEL     → model to use (default: claude-sonnet-4-5)

Note: ANTHROPIC_AUTH_TOKEN is used by Claude Code internally and cannot be
used for standalone API calls. You need a separate API key from
https://console.anthropic.com/
"""

import json
import os
import ssl
import time
from pathlib import Path
from typing import Optional

# Load .env from project root if present (so nohup/cron inherit config)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.error


def _get_ssl_ctx():
    for cert_path in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
        if os.path.exists(cert_path):
            return ssl.create_default_context(cafile=cert_path)
    return ssl._create_unverified_context()


def _get_api_key() -> str:
    """
    Get API key from environment. Checks PAPER_DAILY_API_KEY first,
    then ANTHROPIC_API_KEY. Does NOT use ANTHROPIC_AUTH_TOKEN (that's
    a Claude Code session token, not a standalone API key).
    """
    key = os.environ.get("PAPER_DAILY_API_KEY", "")
    if key:
        return key
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    raise RuntimeError(
        "\n[ERROR] No API key configured for paper-daily scripts.\n"
        "The ANTHROPIC_AUTH_TOKEN is a Claude Code session token and cannot be\n"
        "used for standalone API calls.\n\n"
        "Please set one of:\n"
        "  export PAPER_DAILY_API_KEY='sk-ant-...'\n"
        "  export ANTHROPIC_API_KEY='sk-ant-...'\n\n"
        "Get your key at: https://console.anthropic.com/\n"
    )


def _get_base_url() -> str:
    url = os.environ.get("PAPER_DAILY_BASE_URL",
          os.environ.get("ANTHROPIC_BASE_URL_FOR_SCRIPTS", "https://api.anthropic.com"))
    return url.rstrip("/")


def _get_model() -> str:
    return os.environ.get("PAPER_DAILY_MODEL", "claude-sonnet-4-5")


def call_claude(
    prompt: str,
    model: str = None,
    max_tokens: int = 8192,
    system: Optional[str] = None,
    temperature: float = 0.3,
    retries: int = 3,
) -> str:
    """
    Call Claude API with a single user message.
    Returns the assistant's text response.
    Retries up to `retries` times on transient 5xx errors with exponential backoff.
    Raises RuntimeError on API error after all retries exhausted.
    """
    if model is None:
        model = _get_model()

    base_url = _get_base_url()
    api_key = _get_api_key()

    messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "User-Agent": "claude-code/1.0",
    }

    last_error = None
    for attempt in range(retries + 1):
        if attempt > 0:
            wait = 10 * (2 ** (attempt - 1))  # 10s, 20s, 40s
            print(f"  [retry {attempt}/{retries}] waiting {wait}s...", flush=True)
            time.sleep(wait)

        try:
            if HAS_REQUESTS:
                r = _requests.post(
                    f"{base_url}/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=180,
                )
                if not r.ok:
                    status = r.status_code
                    err = RuntimeError(f"Claude API HTTP {status}: {r.text[:500]}")
                    if status in (429, 502, 503, 504) and attempt < retries:
                        last_error = err
                        continue
                    raise err
                data = r.json()
            else:
                import urllib.request, urllib.error
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}/v1/messages",
                    data=body,
                    method="POST",
                    headers=headers,
                )
                ctx = _get_ssl_ctx()
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    body_text = e.read().decode("utf-8", errors="replace")
                    err = RuntimeError(f"Claude API HTTP {e.code}: {body_text[:500]}")
                    if e.code in (429, 502, 503, 504) and attempt < retries:
                        last_error = err
                        continue
                    raise err

            # Extract text from response
            content = data.get("content", [])
            texts = [block["text"] for block in content if block.get("type") == "text"]
            if not texts:
                raise RuntimeError(f"No text in Claude response: {json.dumps(data)[:300]}")
            return "".join(texts)

        except RuntimeError:
            raise
        except Exception as e:
            err = RuntimeError(f"Claude API error: {e}")
            if attempt < retries:
                last_error = err
                continue
            raise err

    raise last_error


def load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")
    path = os.path.join(prompts_dir, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
