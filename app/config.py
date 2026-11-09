from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    GNANI_API_KEY: str = ""
    GNANI_BASE_URL: str = "https://api.vachana.ai"
    GNANI_MAX_CONCURRENCY: int = 1
    GNANI_TIMEOUT_S: float = 30

    STT_MODEL: Literal["v2.5", "v3.0"] = "v2.5"
    STT_LANGUAGE: str = "ta-IN"
    STT_FORMAT: Literal["transcribe", "verbatim", "codemix", "transliterate"] = "transcribe"
    STT_BIAS_SCORE: float = 1.0
    STT_V3_TOPIC: str = "Cyber fraud complaint: bank, UPI, amount, phone number, transaction ID, time"

    TTS_MODEL: str = "timbre-v2.5"
    TTS_VOICE_TA: str = "Asmita"
    TTS_VOICE_EN: str = "Kaveri"
    TTS_SPEED_PROMPT: float = 1.15  # Timbre allows 0.85-1.15; the caller page plays faster on top
    TTS_SPEED_READBACK: float = 1.0
    TTS_SAMPLE_RATE: int = 24000

    EVON_MODE: Literal["off", "openai_compat"] = "off"
    EVON_BASE_URL: str = "http://localhost:8000/v1"
    EVON_MODEL: str = "model"
    EVON_TIMEOUT_S: float = 8

    APP_NAME: str = "CyberDesk"
    SESSION_TTL_S: int = 1800
    PACKET_TTL_S: int = 86400
    MAX_CLIP_S: float = 25  # largest piece sent to Prisma in one request (Prisma's own limit is 30 s)
    MAX_TURN_S: float = 300  # safety cap on one spoken turn; longer turns are split into MAX_CLIP_S pieces
    MAX_TXNS: int = 1
    MAX_TURNS_PER_CALL: int = 60
    SILENCE_HANDOFF_COUNT: int = 2
    QUEUE_MAX_WAIT_S: int = 300  # an item waiting longer than this jumps to the top (FIFO among overdue)
    OPERATOR_TOKEN: str = ""  # shared secret for operator.html + /api/operator/*; empty = operator API disabled
    DAILY_SESSION_CAP: int = 40
    PER_IP_SESSIONS_PER_HOUR: int = 6
    CACHE_DIR: str = ".cache"
    DEMO_MODE: bool = True
    # Set false in tests / offline dev to skip TTS for dynamic prompts.
    TTS_ENABLED: bool = True

    # --- privacy / security
    # Live user audio is unique, so caching its transcript only writes spoken PII to disk. Bench/probe still cache.
    STT_CACHE_LIVE: bool = False
    STT_LANGUAGE_EN: str = "en-IN"  # STT language when the session UI language is English
    MAX_ACTIVE_SESSIONS: int = 500
    EPHEMERAL_AUDIO_TTL_S: int = 600  # read-back audio (contains the user's digits) lives in memory only
    TRUST_PROXY_HEADERS: bool = False
    HSTS: bool = False
    ENABLE_DOCS: bool = False
    LOG_FILE: str = ""  # e.g. logs/app.log; empty = stdout only
    FFMPEG_TIMEOUT_S: float = 15

    # --- experimental telephony (CLAUDE.md §6.16). Routes are mounted only when enabled.
    TWILIO_ENABLED: bool = False
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_PUBLIC_URL: str = ""  # e.g. https://abc.ngrok-free.app; empty = taken from the request headers
    TWILIO_LANG: Literal["ta", "en"] = "ta"


@lru_cache
def get_settings() -> Settings:
    return Settings()
