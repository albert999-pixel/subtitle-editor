"""Russian word timestamps from local faster-whisper or the Groq API."""


def transcribe_with_local_model(tmp_path, model_path):
    """
    Транскрибирует аудио локально через faster-whisper (без интернета).

    Аргументы:
        tmp_path   — путь к аудиофайлу на диске
        model_path — путь к папке с установленной локальной моделью

    Возвращает:
        список слов: [{"word": "...", "start": float, "end": float}, ...]

    Выбрасывает RuntimeError если faster-whisper не установлен.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Установи: pip install faster-whisper")

    wm = WhisperModel(model_path, device="cpu", compute_type="int8")
    segments, _ = wm.transcribe(str(tmp_path), language="ru", word_timestamps=True)

    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

    return words


GROQ_MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")


def transcribe_with_groq(tmp_path, api_key, model):
    """Request Russian word timestamps, returning the same shape as local Whisper."""
    from groq import Groq, APIConnectionError, APIStatusError

    try:
        with Groq(api_key=api_key, timeout=120, max_retries=1) as client:
            with open(tmp_path, "rb") as audio:
                result = client.audio.transcriptions.create(
                    file=audio,
                    model=model,
                    language="ru",
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                    temperature=0,
                )
    except APIConnectionError:
        raise RuntimeError("Не удалось связаться с Groq. Проверь интернет и попробуй снова.") from None
    except APIStatusError as error:
        body = error.body if isinstance(error.body, dict) else {}
        details = body.get("error", body)
        code = details.get("code") if isinstance(details, dict) else None
        messages = {
            401: "Groq: неверный API-ключ. Проверь ключ в настройках.",
            403: "Groq отклонил запрос (HTTP 403). Проверь разрешения модели в аккаунте Groq и доступность сервиса из текущей сети.",
            413: "Groq: файл слишком большой для твоего тарифа.",
            429: "Groq: достигнут лимит запросов. Попробуй позже.",
        }
        if error.status_code == 403:
            if code in ("model_permission_blocked_org", "model_permission_blocked_project"):
                messages[403] = f"Groq: модель {model} запрещена в настройках организации или проекта. Разреши её в Groq Console → Settings → Limits."
            elif code == "unsupported_country_region_territory":
                messages[403] = "Groq: сервис недоступен для страны или региона текущего подключения. Проверь доступность Groq в своём регионе."
        raise RuntimeError(messages.get(error.status_code, "Groq не смог обработать аудио. Попробуй позже или выбери локальную модель.")) from None
    words = result.model_dump().get("words") or []
    if not words:
        raise RuntimeError("Groq не вернул слова с таймингами. Проверь, что в аудио есть речь.")
    return [{"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])} for w in words]
