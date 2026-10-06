FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SUBTITLE_CONFIG_DIR=/data SUBTITLE_MODELS_DIR=/models SUBTITLE_TEMP_DIR=/tmp/subtitle
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY app.py config.py transcription.py srt.py ai_split.py ./
COPY web/ ./web/
COPY prompts/ ./prompts/
RUN useradd --create-home --uid 1000 subtitle \
    && mkdir -p /data /models /tmp/subtitle && chown -R subtitle:subtitle /data /models /tmp/subtitle
USER subtitle
EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/api/health', timeout=2)" || exit 1
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5001"]
