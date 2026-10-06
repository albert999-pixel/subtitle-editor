#!/usr/bin/env python3
"""
Браузерный интерфейс генератора субтитров
Запуск: python3 app.py
"""
import os
import shutil
from threading import Thread
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from ai_split import suggest_split

from config import init as init_config, load_config, save_config
from transcription import transcribe_with_local_model, transcribe_with_groq, GROQ_MODELS
from srt import build_srt_content

# ─── Пути ──────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
WEB_DIR     = SCRIPT_DIR / "web"

ENV_PATH   = Path(os.environ.get("SUBTITLE_CONFIG_DIR", SCRIPT_DIR)) / ".env"
TEMP_DIR   = Path(os.environ.get("SUBTITLE_TEMP_DIR", SCRIPT_DIR / "temp"))
MODELS_DIR = Path(os.environ.get("SUBTITLE_MODELS_DIR", SCRIPT_DIR / "models"))

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".webm"}
AUDIO_FORMAT_MESSAGE = "Выбери аудиофайл: MP3, M4A, MP4, WAV, FLAC, OGG или WEBM. SRT — файл субтитров, его нельзя транскрибировать."


def validate_audio(path):
    """Read an audio frame before sending an upload to a transcription provider."""
    import av
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio or next(container.decode(audio=0), None) is None:
                raise ValueError()
    except (av.FFmpegError, ValueError):
        raise HTTPException(400, "Файл не содержит читаемого аудио или повреждён. Выбери другой аудиофайл.") from None


# ─── Инициализация FastAPI и модулей ───────────────────────
app = FastAPI()

TEMP_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)

init_config(ENV_PATH)

# Глобальный статус транскрибации — читается маршрутом /api/status
transcription_status = {"status": "idle", "message": "", "words": [], "text": ""}

@app.get("/api/health")
def health():
    return {"application": "subtitle-editor", "status": "ok"}

# ─── Модели тела запроса (Pydantic) ────────────────────────
# FastAPI использует эти классы чтобы автоматически читать и проверять JSON

class ConfigUpdate(BaseModel):
    """Тело запроса для POST /api/config"""
    provider: Optional[str] = None
    groq_model: Optional[str] = None
    groq_api_key: Optional[str] = None

class SrtRequest(BaseModel):
    """Тело запроса для POST /api/build-srt"""
    lines: list   # строки субтитров из интерфейса
    words: list   # слова с таймингами от транскрибации

class SplitRequest(BaseModel):
    texts: list[str]
    max_chars: int = Field(default=24, ge=1, le=99)
    previous_ends: Optional[list[int]] = Field(default=None, max_length=600)

@app.post("/api/ai-split")
def ai_split(data: SplitRequest):
    key = load_config()["GROQ_API_KEY"]
    if not key:
        raise HTTPException(400, "Сначала сохрани API-ключ Groq в настройках")
    try:
        return suggest_split(data.texts, data.max_chars, key, data.previous_ends)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None

# ─── Маршруты: настройки ───────────────────────────────────

@app.get("/api/config")
def get_config():
    """Возвращает текущие настройки."""
    config = load_config()
    return {
        "provider": config["TRANSCRIPTION_PROVIDER"],
        "groq_model": config["GROQ_MODEL"],
        "groq_key_set": bool(config["GROQ_API_KEY"]),
    }

@app.post("/api/config")
def set_config(data: ConfigUpdate):
    """Сохраняет режим транскрибации, облачную модель и API-ключ."""
    config = load_config(include_environment=False)

    if data.groq_api_key is not None and "GROQ_API_KEY" in os.environ:
        raise HTTPException(409, "Ключ задан переменной окружения. Измени её и перезапусти приложение.")
    if data.provider is not None:
        if data.provider not in ("local", "groq"):
            raise HTTPException(400, "Неизвестный режим транскрибации")
        config["TRANSCRIPTION_PROVIDER"] = data.provider
    if data.groq_model is not None:
        if data.groq_model not in GROQ_MODELS:
            raise HTTPException(400, "Неизвестная модель Groq")
        config["GROQ_MODEL"] = data.groq_model
    if data.groq_api_key is not None:
        key = data.groq_api_key.strip()
        if any(c.isspace() for c in key):
            raise HTTPException(400, "API-ключ не должен содержать пробелы или переносы строк")
        config["GROQ_API_KEY"] = key
    save_config(config)
    return {"ok": True}

# ─── Маршруты: транскрибация ───────────────────────────────

@app.get("/api/local-models")
def list_local_models():
    """Возвращает список локальных моделей из папки models/."""
    if not MODELS_DIR.exists():
        return {"models": []}
    models = []
    for p in sorted(MODELS_DIR.iterdir()):
        if not p.name.startswith(".") and p.is_dir() and (p / "config.json").exists():
            models.append(p.name)
    return {"models": models}

@app.post("/api/transcribe")
async def transcribe(
    file:  UploadFile = File(...),
    model: str = Form(""),   # имя локальной модели из папки models/
    provider: str = Form("local"),
    groq_model: str = Form("whisper-large-v3-turbo"),
):
    """
    Запускает транскрибацию аудиофайла в фоновом потоке.
    Результат можно забрать через /api/status.
    """
    global transcription_status

    config = load_config()
    if transcription_status["status"] == "processing":
        raise HTTPException(409, "Дождись окончания текущей транскрибации")
    audio_ext = Path(file.filename or "").suffix.lower()
    if audio_ext not in AUDIO_EXTENSIONS:
        raise HTTPException(400, AUDIO_FORMAT_MESSAGE)
    if not file.size:
        raise HTTPException(400, "Файл пустой. Выбери аудиофайл с записью.")
    if provider not in ("local", "groq"):
        raise HTTPException(400, "Неизвестный режим транскрибации")
    if provider == "groq":
        if not config["GROQ_API_KEY"]:
            raise HTTPException(400, "Сначала сохрани API-ключ Groq в настройках")
        if groq_model not in GROQ_MODELS:
            raise HTTPException(400, "Неизвестная модель Groq")
    else:
        if not model:
            raise HTTPException(400, "Скачай и выбери локальную модель или переключись на Groq")
        candidate = (MODELS_DIR / model).resolve()
        if candidate.parent != MODELS_DIR.resolve() or not (candidate / "config.json").is_file():
            raise HTTPException(400, "Локальная модель не найдена")

    audio_path = TEMP_DIR / f"current_audio{audio_ext}"
    tmp_path = TEMP_DIR / f"_tmp_{uuid4().hex}{audio_ext}"
    tmp_path.write_bytes(await file.read())
    try:
        await run_in_threadpool(validate_audio, tmp_path)
        if transcription_status["status"] == "processing":
            raise HTTPException(409, "Дождись окончания текущей транскрибации")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # Keep the previous playable audio when an invalid upload is rejected.
    for old_audio in TEMP_DIR.glob("current_audio.*"):
        try:
            old_audio.unlink()
        except OSError:
            pass

    transcription_status = {"status": "processing", "message": "Транскрибирую...", "words": [], "text": ""}

    def run():
        """Выполняется в отдельном потоке чтобы не блокировать сервер."""
        global transcription_status
        try:
            model_path = str(MODELS_DIR / model)
            if provider == "groq":
                words = transcribe_with_groq(tmp_path, config["GROQ_API_KEY"], groq_model)
            else:
                words = transcribe_with_local_model(tmp_path, model_path)

            text = " ".join(w["word"] for w in words)
            transcription_status = {"status": "done", "message": f"Готово! {len(words)} слов", "words": words, "text": text}

        except Exception as e:
            transcription_status = {"status": "error", "message": f"Ошибка: {e}", "words": [], "text": ""}

        finally:
            # Перемещаем файл в temp/ чтобы плеер мог его воспроизвести
            if tmp_path.exists():
                shutil.copy2(tmp_path, audio_path)
                tmp_path.unlink()

    Thread(target=run, daemon=True).start()
    return {"ok": True}

@app.get("/api/status")
def status():
    """Возвращает текущий статус транскрибации."""
    return transcription_status

# ─── Маршруты: субтитры ────────────────────────────────────

@app.post("/api/build-srt")
def build_srt(data: SrtRequest):
    """Собирает SRT файл из строк субтитров и слов с таймингами."""
    if not data.lines:
        return {"error": "Нет данных"}

    srt_content, count = build_srt_content(data.lines, data.words)
    return {"srt": srt_content, "count": count}

# ─── Маршруты: аудио ───────────────────────────────────────

@app.get("/api/audio")
def get_audio():
    """Отдаёт текущий аудиофайл для плеера."""
    files = list(TEMP_DIR.glob("current_audio.*"))
    if not files:
        return FileResponse(status_code=404, path="")
    audio_file = files[0]
    mime_map = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav",  ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",  ".flac": "audio/flac", ".webm": "audio/webm",
    }
    mime = mime_map.get(audio_file.suffix.lower(), "audio/mpeg")
    return FileResponse(str(audio_file), media_type=mime)

@app.get("/api/audio-ready")
def audio_ready():
    """Проверяет есть ли аудиофайл для плеера."""
    files = list(TEMP_DIR.glob("current_audio.*"))
    return {"ready": len(files) > 0}

# ─── Статические файлы (фронтенд) ──────────────────────────
# Монтируется последним — все /api/* маршруты выше имеют приоритет
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

# ─── Запуск ────────────────────────────────────────────────
if __name__ == "__main__":
    from scripts.manage import start
    start(5002)
