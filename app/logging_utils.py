"""Structured JSON logging. Every log line passes through mask() so raw PII never lands in logs."""

import json
import logging
import re
import sys
import time

# Any run of 6+ digits (optionally with spaces/commas/hyphens inside) is treated as PII.
_DIGIT_RUN = re.compile(r"(?<!\w)(?:\+?\d[\d ,\-]{4,}\d)(?!\w)")
_VPA = re.compile(r"\b([\w.\-]{2,})@([a-zA-Z]{2,64})\b")
_RUPEE = re.compile(r"(₹|Rs\.?|INR)\s?[\d,]+(?:\.\d+)?", re.IGNORECASE)
# Session ids and audio tokens in request paths: each one opens that call's data, so logs keep a short prefix.
_TOKEN = re.compile(r"\b[0-9a-f]{32,}\b")


def mask_digits(d: str) -> str:
    """'9876543210' -> '98•••••210'; keeps first 2 and last 3 (or last 4 for >=12 digits)."""
    if len(d) <= 4:
        return "•" * len(d)
    if len(d) >= 12:
        return d[:4] + "•" * (len(d) - 8) + d[-4:]
    return d[:2] + "•" * (len(d) - 5) + d[-3:]


def mask(text: object) -> str:
    s = _TOKEN.sub(lambda m: f"{m.group(0)[:8]}…", str(text))
    s = _RUPEE.sub(lambda m: f"{m.group(1)}•••", s)

    def _run(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 6:
            return m.group(0)
        return mask_digits(digits)

    s = _DIGIT_RUN.sub(_run, s)
    s = _VPA.sub(lambda m: f"{m.group(1)[:2]}•••@{m.group(2)}", s)
    return s


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask(record.getMessage()),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update({k: mask(v) for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = mask(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> None:
    """JSON logs to stdout, plus a rotating file when LOG_FILE is set. Every line goes through mask()."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    from app.config import get_settings

    log_file = log_file if log_file is not None else get_settings().LOG_FILE
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(JsonFormatter())
    root.handlers = handlers
    root.setLevel(level)
    # uvicorn's access log carries only method, path and status: route it through the same masking formatter
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


def log(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"extra_fields": fields})
