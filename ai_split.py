"""Suggest caption boundaries. Text is always reconstructed locally, never by LLM."""
import json
from pathlib import Path

MODEL = "openai/gpt-oss-120b"
PROMPT_PATH = Path(__file__).parent / "prompts" / "subtitle_split.md"
MAX_WORDS = 600
MAX_TEXT_CHARS = 10_000


def validate_boundaries(words, ends):
    if not isinstance(ends, list) or not ends or any(type(n) is not int for n in ends):
        raise ValueError("ИИ вернул некорректные границы. Исходные титры сохранены.")
    previous = 0
    lines = []
    for end in ends:
        if not previous < end <= len(words):
            raise ValueError("ИИ нарушил порядок границ. Исходные титры сохранены.")
        text = " ".join(words[previous:end])
        lines.append(text)
        previous = end
    if previous != len(words):
        raise ValueError("ИИ не включил весь текст. Исходные титры сохранены.")
    return lines


def preview_response(words, raw_response, max_chars, finish_reason):
    """Keep every received answer visible; repair boundaries without changing words."""
    warnings = []
    if finish_reason != "stop":
        warnings.append(f"Ответ завершился с причиной {finish_reason or 'не указана'}; показан полученный фрагмент.")
    try:
        data = json.loads(raw_response)
        raw_ends = data.get("ends") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        raw_ends = None
        warnings.append("Ответ не удалось разобрать как JSON. Исходный ответ показан ниже.")
    if not isinstance(raw_ends, list):
        warnings.append("Нет списка ends. Для предпросмотра весь текст оставлен одним титром.")
        raw_ends = []
    accepted = []
    for index, end in enumerate(raw_ends, 1):
        if type(end) is not int:
            warnings.append(f"Граница №{index}: {end!r} — не целое число, пропущена.")
        elif not 1 <= end <= len(words):
            warnings.append(f"Граница №{index}: {end} вне диапазона 1–{len(words)}, пропущена.")
        else:
            accepted.append(end)
    ends = sorted(set(accepted))
    if accepted != ends:
        warnings.append("Границы упорядочены; повторяющиеся позиции удалены.")
    if not ends or ends[-1] != len(words):
        ends.append(len(words))
        warnings.append(f"Добавлена последняя граница {len(words)}, чтобы сохранить весь текст.")
    lines = validate_boundaries(words, ends)
    overlong = [{"index": i + 1, "length": len(text)} for i, text in enumerate(lines) if len(text) > max_chars]
    return {"lines": lines, "ends": ends, "model": MODEL, "overlong": overlong,
            "max_chars": max_chars, "warnings": warnings, "raw_response": raw_response,
            "finish_reason": finish_reason}


def suggest_split(texts, max_chars, api_key, previous_ends=None):
    words = [word for text in texts for word in text.split()]
    if not words:
        raise ValueError("Сначала загрузи текст в редактор.")
    if len(words) > MAX_WORDS or len(" ".join(words)) > MAX_TEXT_CHARS:
        raise ValueError("Экспериментальный режим принимает до 600 слов и 10 000 символов за один запрос.")
    from groq import Groq, APIConnectionError, APIStatusError
    schema = {"type": "object", "properties": {"ends": {"type": "array", "items": {"type": "integer"}}},
              "required": ["ends"], "additionalProperties": False}
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        raise ValueError("Не удалось прочитать prompts/subtitle_split.md") from None
    try:
        with Groq(api_key=api_key, timeout=90, max_retries=0) as client:
            result = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": prompt},
                          {"role": "user", "content": json.dumps({"max_chars": max_chars, "word_count": len(words), "words": [{"index": i, "text": word} for i, word in enumerate(words, 1)], "previous_ends": previous_ends}, ensure_ascii=False)}],
                response_format={"type": "json_schema", "json_schema": {"name": "caption_boundaries", "strict": True, "schema": schema}},
                reasoning_effort="low",
                temperature=0.8,
                max_completion_tokens=2048,
            )
    except APIConnectionError:
        raise ValueError("Не удалось связаться с Groq. Исходные титры сохранены.") from None
    except APIStatusError as error:
        if error.status_code == 429:
            message = "Groq: достигнут лимит запросов или токенов. Попробуй позже."
        elif error.status_code in (401, 403):
            message = "Groq: проверь API-ключ и доступ к GPT OSS 120B."
        else:
            message = "Groq не смог выполнить разбивку. Исходные титры сохранены."
        raise ValueError(message) from None
    choice = result.choices[0] if result.choices else None
    raw_response = (choice.message.content or "") if choice else ""
    finish_reason = choice.finish_reason if choice else None
    return preview_response(words, raw_response, max_chars, finish_reason)
