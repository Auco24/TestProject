# ⚡ Dev Toolkit

Локальный набор утилит для ежедневной работы программиста. Работает **полностью офлайн**: ваши JSON, токены и пароли никуда не уходят.

Есть веб-интерфейс (светлая и тёмная тема, поиск по `Ctrl+K`) и CLI для терминала.

![JSON](docs/screenshots/json.png)

## Возможности

| Инструмент | Что умеет |
|---|---|
| **JSON** | форматирование, минификация, сортировка ключей, подсветка, ошибки с номером строки |
| **JWT** | раскодирует header и payload, показывает статус (действителен / истёк) и даты `iat`/`nbf`/`exp` |
| **Base64 / URL** | кодирование и декодирование, URL-safe Base64, кнопка «поменять местами» |
| **Timestamp** | Unix (с / мс / мкс) ↔ ISO-дата, любой часовой пояс, «2 часа назад» |
| **Regex** | живая подсветка совпадений, группы и именованные группы, флаги `i m s x` |
| **Генераторы** | надёжные пароли с оценкой энтропии, UUID v4, хэши MD5/SHA1/SHA256/SHA512 |

### 📋 Сниппеты

Храните команды и куски кода, которые постоянно гуглите, и находите их за секунду.

![Snippets](docs/screenshots/snippets.png)

- поиск по всем полям; `#тег` фильтрует по тегу, `lang:python` по языку;
- теги, избранное, сортировка по недавним, популярным или алфавиту;
- подсветка синтаксиса для 18 языков, номера строк;
- счётчик использований: часто копируемые сниппеты поднимаются выше;
- **`Ctrl+K` из любого места** ищет и сразу копирует сниппет;
- импорт и экспорт в JSON, набор полезных примеров для старта;
- данные хранятся в SQLite: `~/.devtool/devtool.sqlite3`, путь меняется через переменную `DEVTOOL_DB`.

Горячие клавиши в модуле: `/` поиск · `↑↓` или `j`/`k` навигация · `Enter` копировать · `N` новый · `E` редактировать · `F` избранное · `Ctrl+Enter` сохранить · `Esc` отмена.

Следующие модули: **Дневник разработчика**, **Git-дашборд**.

<details>
<summary>Ещё скриншоты</summary>

![JWT](docs/screenshots/jwt.png)
![Regex](docs/screenshots/regex.png)
![Generators](docs/screenshots/generators-light.png)
![Snippet editor](docs/screenshots/snippets-editor.png)
![Command palette](docs/screenshots/palette.png)

</details>

## Установка

Нужен Python 3.10+.

```bash
git clone https://github.com/Auco24/TestProject.git
cd TestProject
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Запуск

```bash
devtool start
```

Браузер откроется на <http://127.0.0.1:8000>. Опции: `--port 9000`, `--no-browser`.

## CLI

```bash
devtool json '{"a":1,"b":[1,2]}'          # форматировать
cat data.json | devtool json --minify      # минифицировать из stdin
devtool jwt eyJhbGciOi...                  # раскодировать JWT
devtool b64 "Привет"                       # → 0J/RgNC40LLQtdGC
devtool b64 -d 0J/RgNC40LLQtdGC            # → Привет
devtool url "a b&c"                        # → a%20b%26c
devtool ts                                 # текущее время во всех форматах
devtool ts 1730505600 --tz Europe/Berlin   # timestamp → дата
devtool regex '\d+' "a1 b22 c333"          # проверить regex
devtool hash "hello" -a sha256             # хэш
devtool uuid -n 5                          # 5 UUID
devtool pass -l 32                         # пароль из 32 символов
```

### Сниппеты в терминале

```bash
devtool snip add "docker ps -a" -t "Все контейнеры" -g docker
cat script.sh | devtool snip add - -t "Деплой" -l bash -g deploy
devtool snip add                           # откроет $EDITOR
devtool snip find docker                   # поиск
devtool snip find "#git" --sort popular    # по тегу, популярные сверху
devtool snip show 3                        # показать
devtool snip copy 3                        # в буфер обмена
devtool snip edit 3                        # редактировать в $EDITOR
devtool snip fav 3 / rm 3 / tags
devtool snip export backup.json            # экспорт
devtool snip import backup.json            # импорт (дубликаты пропускаются)
```

`devtool --help` и `devtool <команда> --help` показывают все опции.

## Разработка

```bash
pip install -e ".[dev]"
pytest
```

API-документация (Swagger) открывается на <http://127.0.0.1:8000/api/docs>, пока сервер запущен.

### Структура

```
devtool/
├── tools.py        # утилиты: чистые функции без зависимостей
├── db.py           # SQLite: подключение и миграции
├── snippets.py     # сниппеты: CRUD, поиск, теги, импорт/экспорт
├── clipboard.py    # буфер обмена без внешних зависимостей
├── api.py          # FastAPI: /api/tools/*, /api/snippets/* + интерфейс
├── cli.py          # Typer CLI
└── static/         # интерфейс: HTML + CSS + JS, без внешних CDN
    ├── app.js      #   утилиты, навигация, Ctrl+K
    └── snippets.js #   модуль сниппетов + подсветка синтаксиса
tests/              # pytest: tools, API, CLI
```

Чтобы добавить новый инструмент:
1. Напишите функцию в `tools.py`.
2. Зарегистрируйте её в `HANDLERS` в `api.py`.
3. Добавьте `<section class="tool">` в `index.html` и обработчик в `app.js`.
