"""Ask for readable captions, then project their breaks onto the original words."""
import json
from difflib import SequenceMatcher
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


def _project_line_ends(words, proposed_lines):
    """Map proposed breaks to original word positions, including omissions/insertions."""
    proposed_words, proposed_ends = [], []
    for line in proposed_lines:
        proposed_words.extend(line.split())
        proposed_ends.append(len(proposed_words))
    if proposed_words == words:
        return proposed_ends
    def match_token(word):
        return word.casefold().strip('.,!?;:«»"…()[]—-') or word.casefold()
    matcher = SequenceMatcher(None, [match_token(w) for w in words],
                              [match_token(w) for w in proposed_words], autojunk=False)
    if not any(block.size for block in matcher.get_matching_blocks()):
        return []
    positions = [0] * (len(proposed_words) + 1)
    for _, src_start, src_end, dst_start, dst_end in matcher.get_opcodes():
        if dst_end == dst_start:
            positions[dst_start] = src_end
        else:
            for index in range(dst_start, dst_end + 1):
                positions[index] = src_start + round(
                    (index - dst_start) * (src_end - src_start) / (dst_end - dst_start))
    return [positions[end] for end in proposed_ends]


DANGLING_WORDS = {'в', 'на', 'с', 'к', 'из', 'по', 'для', 'о', 'от', 'до', 'у',
                  'за', 'над', 'под', 'при', 'без', 'и', 'а', 'но', 'или', 'чтобы', 'не'}


def preview_response(words, raw_response, max_chars, finish_reason):
    """Show the raw answer even on failure; apply breaks only to original text."""
    warnings = []
    if finish_reason != "stop":
        warnings.append(f"Ответ завершился с причиной {finish_reason or 'не указана'}; показан полученный фрагмент.")
    try:
        data = json.loads(raw_response)
        proposals = data.get("lines") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        proposals = None
        warnings.append("Ответ не удалось разобрать как JSON. Исходный ответ показан ниже.")
    if not isinstance(proposals, list):
        warnings.append("Нет списка lines. Для предпросмотра весь текст оставлен одним титром.")
        proposals = []
    usable = [line for line in proposals if isinstance(line, str) and line.split()]
    if len(usable) != len(proposals):
        warnings.append("Пустые строки и элементы, не являющиеся текстом, пропущены.")
    proposed_words = [word for line in usable for word in line.split()]
    if proposed_words != words:
        warnings.append("Ответ отличается от исходного текста: в предпросмотре восстановлены исходные слова, регистр и пунктуация. Границы сопоставлены приблизительно.")
    projected = _project_line_ends(words, usable)
    ends = sorted(set(end for end in projected if 0 < end <= len(words)))
    if not ends:
        warnings.append("Не удалось сопоставить строки с исходным текстом. Весь текст оставлен одним титром.")
    elif len(ends) != len(usable):
        warnings.append("Строки без отдельного диапазона исходных слов объединены с соседними.")
    if not ends or ends[-1] != len(words):
        ends.append(len(words))
    lines = validate_boundaries(words, ends)
    overlong = [{"index": i + 1, "length": len(text)} for i, text in enumerate(lines) if len(text) > max_chars]
    quality_warnings = [{"index": i + 1, "reason": "связующее слово в конце"}
                        for i, text in enumerate(lines[:-1])
                        if text.split()[-1].casefold().strip('.,!?;:') in DANGLING_WORDS]
    return {"lines": lines, "ends": ends, "model": MODEL, "overlong": overlong,
            "max_chars": max_chars, "warnings": warnings, "quality_warnings": quality_warnings,
            "raw_response": raw_response, "finish_reason": finish_reason}


def suggest_split(texts, max_chars, api_key, previous_ends=None):
    words = [word for text in texts for word in text.split()]
    if not words:
        raise ValueError("Сначала загрузи текст в редактор.")
    if len(words) > MAX_WORDS or len(" ".join(words)) > MAX_TEXT_CHARS:
        raise ValueError("Экспериментальный режим принимает до 600 слов и 10 000 символов за один запрос.")
    from groq import Groq, APIConnectionError, APIStatusError
    schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
              "required": ["lines"], "additionalProperties": False}
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        raise ValueError("Не удалось прочитать prompts/subtitle_split.md") from None
    previous_lines = None
    if previous_ends:
        # Regeneration gets readable phrases rather than another numerical pattern.
        try:
            previous_lines = validate_boundaries(words, previous_ends)
        except ValueError:
            pass
    try:
        with Groq(api_key=api_key, timeout=90, max_retries=0) as client:
            result = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": prompt},
                          {"role": "user", "content": json.dumps({"max_chars": max_chars, "text": " ".join(words), "previous_lines": previous_lines}, ensure_ascii=False)}],
                response_format={"type": "json_schema", "json_schema": {"name": "caption_lines", "strict": True, "schema": schema}},
                reasoning_effort="low",
                temperature=0.35,
                max_completion_tokens=4096,
            )
    except APIConnectionError:
        raise ValueError("Не удалось связаться с Groq. Исходные титры сохранены.") from None
    except APIStatusError as error:
        body = error.body if isinstance(error.body, dict) else {}
        details = body.get("error", body)
        details = details if isinstance(details, dict) else {}
        if details.get("code") == "json_validate_failed":
            generated = details.get("failed_generation")
            if isinstance(generated, str) and generated:
                return preview_response(words, generated, max_chars, "json_validate_failed")
            message = "Groq не вернул ответ в формате JSON. Попробуй перегенерировать; исходные титры сохранены."
        elif error.status_code == 429:
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
