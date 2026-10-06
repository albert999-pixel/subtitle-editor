# Локальные модели

Для Groq (облачное распознавание) эта папка не нужна. Для локального
распознавания положите сюда модель **faster-whisper в формате CTranslate2**.
Модели скачиваются вручную через браузер; скрипта загрузки в проекте нет.

## Ссылки на файлы моделей

| Модель | Files and versions на Hugging Face |
| --- | --- |
| Tiny | https://huggingface.co/Systran/faster-whisper-tiny/tree/main |
| Base | https://huggingface.co/Systran/faster-whisper-base/tree/main |
| Small | https://huggingface.co/Systran/faster-whisper-small/tree/main |
| Medium | https://huggingface.co/Systran/faster-whisper-medium/tree/main |
| Large v3 | https://huggingface.co/Systran/faster-whisper-large-v3/tree/main |
| Large v3 Turbo | https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/main |

Для русского языка выбирайте многоязычную модель, без суффикса `.en`.
Большие модели требуют больше памяти и места на диске. Скорость загрузки
зависит от соединения и сервиса; наличие аккаунта не гарантирует ускорения.
Ссылка Turbo раньше находилась у `mobiuslabsgmbh`; теперь она перенаправляет
на `dropbox-dash`.

## Как скачать через браузер

1. Откройте ссылку на нужную модель. При необходимости войдите в аккаунт
   Hugging Face. API-токен в Subtitle Editor для этих загрузок вводить не нужно.
2. Создайте внутри `models` подпапку с любым понятным названием, например
   `large-v3-turbo` или `small`.
3. Во вкладке **Files and versions** скачайте файлы кнопкой загрузки:
   - `model.bin` — веса модели, самый большой файл;
   - `config.json`;
   - `tokenizer.json`;
   - `vocabulary.json` **или** `vocabulary.txt` — скачайте тот, что есть в репозитории;
   - `preprocessor_config.json`, если есть.
4. Положите все файлы непосредственно в созданную подпапку. Имена и расширения
   файлов менять не нужно. README и `.gitattributes` модели не требуются.
   Дождитесь полного скачивания `model.bin`: временный файл загрузки не подходит.
5. В приложении выберите локальный режим и эту модель в настройках. Если она
   ещё не появилась, обновите страницу. Перед обновлением скачайте текущий SRT:
   правки редактора не сохраняются между обновлениями страницы.

Пример для Large v3 Turbo:

```text
subtitle-editor/
  models/
    README.md
    large-v3-turbo/
      config.json
      model.bin
      preprocessor_config.json
      tokenizer.json
      vocabulary.json
```

Для Small вместо `vocabulary.json` используется `vocabulary.txt`, а
`preprocessor_config.json` на странице модели может отсутствовать.

Можно перенести уже скачанную папку модели с другого компьютера.
Не подходят исходные `.pt`-модели Whisper, GGUF или файлы `safetensors`:
нужна именно конвертированная модель CTranslate2 по ссылкам выше.

Файлы моделей исключены из Git. В репозиторий входит только эта инструкция.
