"""Optional Gnani Evon v3.3 client (self-hosted, OpenAI-compatible). Never used for digits."""

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("gnani.evon")

SYSTEM_PROMPT = (
    "You extract slots from a cyber-fraud victim's statement (Tamil, Tanglish or English). "
    "Output JSON only, with keys: bank, fraud_type, slots{amount_span, suspect_phone_span, "
    "victim_phone_span, utr_span}. fraud_type is one of OTP_BANK_CALL, UPI_COLLECT, DIGITAL_ARREST, "
    "INVESTMENT, JOB_TASK, LOAN_APP, FAKE_CUSTOMER_CARE, OTHER. Copy spans verbatim from the input. "
    "Use null when absent. Never write digits that are not in the input."
)


async def extract(transcript: str, literal: str | None) -> dict[str, Any] | None:
    s = get_settings()
    if s.EVON_MODE == "off":
        return None
    user = f"TRANSCRIPT:\n{transcript}\n\nLITERAL:\n{literal or ''}"
    body = {
        "model": s.EVON_MODEL,
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=s.EVON_TIMEOUT_S) as client:
            r = await client.post(f"{s.EVON_BASE_URL.rstrip('/')}/chat/completions", json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return data if isinstance(data, dict) else None
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        logger.warning("evon fallback to rules", extra={"extra_fields": {"err": type(e).__name__}})
        return None
