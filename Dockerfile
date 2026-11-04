FROM python:3.11-slim

# ffmpeg is fed untrusted audio; the app always runs it with -protocol_whitelist pipe and a timeout.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.32.1" httpx==0.28.1 pydantic==2.10.4 \
    pydantic-settings==2.7.0 python-multipart==0.0.20 numpy==2.4.6 twilio==9.12.0
COPY --chown=app:app app ./app
COPY --chown=app:app static ./static
# the TTS cache of fixed prompts is the only thing written to disk (no user audio, no transcripts)
RUN mkdir -p /app/.cache && chown app:app /app/.cache

USER app
ENV PORT=8080 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')" || exit 1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --no-server-header"]
