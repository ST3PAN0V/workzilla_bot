# Yandex AI Studio LLM: памятка для агентов

Актуально на 2026-08-20. Здесь собрана только информация, полезная для этого
проекта. Секреты в код, документацию, тесты и логи не добавлять.

## Конфигурация проекта

Секреты находятся в корневом `.env`:

```dotenv
YC_API_KEY=...
YC_FOLDER_ID=...
YC_MODEL=yandexgpt-5-lite
# Необязательно:
# YC_MODEL_URI=gpt://<folder-id>/yandexgpt-5-lite/latest
# YC_LLM_ENDPOINT=https://ai.api.cloud.yandex.net/v1/chat/completions
```

Канонический URI модели:

```text
gpt://<folder-id>/yandexgpt-5-lite
```

В проекте используется вариант с `/latest`. YandexGPT Lite 5 доступна через
OpenAI-совместимый Chat Completions API и подходит для недорогой классификации
заказов.

## Как вызвать модель в проекте

```python
from shared_llm.client import ask_llm

answer = await ask_llm(
    "Текст заявки",
    system_prompt="Кратко проанализируй заявку.",
)
```

Проверка реального API и локальных тестов:

```bash
python -m scripts.llm_smoke
python -m unittest discover -s tests -v
```

## Эндпоинты

Официальный base URL новых интеграций:

```text
https://ai.api.cloud.yandex.net/v1
```

Текущий клиент использует совместимый адрес
`https://llm.api.cloud.yandex.net/v1/chat/completions`. Не менять адрес без
smoke-теста.

| Метод и путь | Назначение |
|---|---|
| `GET /models` | Модели, доступные сервисному аккаунту |
| `POST /chat/completions` | Простой независимый запрос; основной вариант проекта |
| `POST /responses` | Новый API: инструменты, файлы, строгий JSON, фоновые ответы |
| `GET /responses/{id}` | Получение сохранённого или фонового ответа |
| `POST /conversations` | Создание сохраняемого диалога |
| `POST /conversations/{id}/items` | Добавление элементов в диалог |

Также существуют `/embeddings`, `/files`, `/vector_stores` и
`/images/generations`, но для них используются соответствующие отдельные модели.

Заголовки REST-запроса:

```text
Authorization: Api-Key <YC_API_KEY>
Content-Type: application/json
x-project: <YC_FOLDER_ID>  # нужен, в частности, для GET /models
```

## Рекомендуемый Chat Completions payload

Для анализа заявок нужен детерминированный короткий ответ. Актуальная модель
проекта — `yandexgpt-5-lite`:

```json
{
  "model": "gpt://<folder-id>/yandexgpt-5-lite/latest",
  "messages": [
    {"role": "system", "content": "Верни результат строго по JSON-схеме."},
    {"role": "user", "content": "<текст заявки>"}
  ],
  "temperature": 0,
  "max_tokens": 300,
  "stream": false,
  "n": 1,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "task_analysis",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "suitable": {"type": "boolean"},
          "reason": {"type": "string"}
        },
        "required": ["suitable", "reason"],
        "additionalProperties": false
      }
    }
  }
}
```

Текущий клиент и промпт классификатора используют роль `system`.

## Полезные настройки

| Настройка | Значение для проекта | Примечание |
|---|---|---|
| `temperature` | `0` или `0.1` | Чем ниже, тем стабильнее классификация |
| `top_p` | не задавать или `1` | Обычно меняют либо его, либо `temperature` |
| `max_tokens` | `200–300` | Достаточно для короткого JSON и причины |
| `stream` | `false` | Для строгого JSON нужно дождаться всего ответа |
| `response_format` | `json_schema`, `strict: true` | Надёжнее просьбы «верни JSON» в промпте |
| `verbosity` | `low` | Поддержка зависит от модели; сначала проверить |
| `tools` / `tool_choice` | пока не нужны | Для вызова функций и внешних действий |
| `n` | `1` | Дополнительные варианты увеличивают расход |
| `seed` | необязательно | Улучшает повторяемость, но не гарантирует её |
| `stop` | обычно не нужен | До четырёх стоп-последовательностей |
| `frequency_penalty`, `presence_penalty` | `0` | Диапазон `-2..2` |

## Когда выбирать Responses API

Оставлять `/chat/completions`, пока нужен один независимый запрос и JSON.
Переходить на `/responses`, когда появятся встроенные инструменты, файлы,
серверная история, `previous_response_id` или фоновые запросы. Аналоги основных
полей: `input`, `instructions`, `reasoning: {"effort": "low"}`,
`max_output_tokens` и `text.format`.

## Частые ошибки

| Ошибка | Что проверить |
|---|---|
| `400 Unsupported parameter` | Название поля и поддержку параметра моделью |
| `401/403` | API-ключ, scope, роль сервисного аккаунта и каталог |
| `404 Unknown model` | Проверить URI модели, каталог и выбранный API |
| Пустой `content` | Проверить лимит токенов и формат ответа |
| Таймаут | Длина промпта, лимит ответа, сеть; разумный timeout — 120 секунд |
| Невалидный JSON | Использовать `response_format=json_schema`, затем валидировать ответ |

Ответ читать из `choices[0].message.content`; скрытые рассуждения могут прийти в
`reasoning_content`, а расход — в `usage`. Рассуждения не логировать и не включать
в бизнес-ответ.

## Официальные ссылки

- [Доступные модели](https://aistudio.yandex.ru/docs/ru/ai-studio/concepts/generation/models.html)
- [Chat Completions](https://aistudio.yandex.ru/docs/ru/ai-studio/api/Chat-Completions/createChatCompletion.html)
- [Responses API](https://aistudio.yandex.ru/docs/ru/ai-studio/api/Responses/createResponse.html)
- [Строгий JSON](https://aistudio.yandex.ru/docs/ru/ai-studio/operations/generation/completions-structured.html)
- [Управление reasoning](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/chain-of-thought.html)
