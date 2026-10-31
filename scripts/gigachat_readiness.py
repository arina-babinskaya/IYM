"""Safe GigaChat configuration check; optionally tests OAuth/model discovery, never generation."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.llm.gigachat import GigaChatClient, GigaChatError


def readiness(settings: Settings) -> dict[str, object]:
    bundle = Path(settings.gigachat_ca_bundle).expanduser() if settings.gigachat_ca_bundle else None
    bundle_exists = bundle.is_file() if bundle else None
    bundle_readable = os.access(bundle, os.R_OK) if bundle_exists and bundle else None
    errors: list[str] = []
    if not settings.gigachat_enabled:
        errors.append("GigaChat is disabled (RC_GIGACHAT_ENABLED=false).")
    if not settings.gigachat_credentials:
        errors.append("RC_GIGACHAT_CREDENTIALS is not configured.")
    if not settings.gigachat_verify_ssl:
        errors.append("SSL verification must remain enabled.")
    for name, value in (("auth URL", settings.gigachat_auth_url), ("API URL", settings.gigachat_api_url)):
        if urlparse(value).scheme != "https":
            errors.append(f"GigaChat {name} must use HTTPS.")
    if bundle and not bundle_exists:
        errors.append("Configured CA bundle does not exist.")
    elif bundle and not bundle_readable:
        errors.append("Configured CA bundle is not readable.")
    elif bundle:
        try:
            ssl.create_default_context(cafile=str(bundle))
        except (OSError, ssl.SSLError):
            errors.append("Configured CA bundle is not a valid PEM certificate bundle.")
    return {
        "ready": not errors,
        "enabled": settings.gigachat_enabled,
        "credentials_configured": bool(settings.gigachat_credentials),
        "ssl_verification": settings.gigachat_verify_ssl,
        "ca_bundle_configured": bundle is not None,
        "ca_bundle_exists": bundle_exists,
        "ca_bundle_readable": bundle_readable,
        "model_configured": bool(settings.gigachat_model.strip()),
        "errors": errors,
    }


async def live_check(settings: Settings) -> dict[str, object]:
    """Explicit free discovery call: OAuth plus GET /models, no completion request."""
    try:
        models = await GigaChatClient(settings).models()
        return {"ok": True, "configured_model_available": settings.gigachat_model in models}
    except GigaChatError as exc:
        return {"ok": False, "error_kind": exc.kind, "step": exc.diagnostic.get("step", "unknown")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="also test OAuth and GET /models (no generation)")
    args = parser.parse_args()
    settings = get_settings()
    report = readiness(settings)
    if args.live and report["ready"]:
        report["live"] = asyncio.run(live_check(settings))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] and (not args.live or report.get("live", {}).get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
