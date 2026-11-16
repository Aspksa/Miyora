# Miyora

Локальное веб-приложение: Python 3.13, SQLite, тёмный интерфейс. Проект организован так, чтобы запуск оставался простым, а модули можно было развивать отдельно.

## Структура

```text
Miyora/
├── start.bat                  # Запуск двойным кликом
├── launcher.ps1               # Поиск и загрузка переносимого Python
├── main.py                    # Совместимая точка входа
├── database.py                # Совместимый импорт базы
├── app/
│   ├── __init__.py
│   ├── server.py              # HTTP API и запуск сервера
│   └── core/
│       ├── __init__.py
│       └── database.py        # SQLite и миграции
├── web/
│   └── index.html             # Интерфейс
├── tests/
│   └── test_smoke.py          # Проверки API и SQLite
├── .github/workflows/
│   └── windows-portable.yml   # Windows CI и сборка EXE
├── runtime/                   # Автоматически скачанный Python; не в Git
│   └── python/
└── data/                      # База и журнал; не в Git
    ├── miyora.db
    └── miyora.log
```

Папки `runtime/` и `data/` создаются автоматически. Не удаляйте `data/`, если нужны сохранённые заметки.

## Запуск Windows

Скачайте весь репозиторий и откройте `start.bat`. При отсутствии `Miyora.exe` запускатор проверяет `runtime/python/python.exe` и, если необходимо, загружает официальную встраиваемую сборку Python с python.org в папку проекта. Первый запуск требует интернет. Windows PowerShell нужен для запуска `launcher.ps1`. Системный Python не изменяется.

Логи запуска: `launcher-diagnostic.txt`; логи сервера: `data/miyora.log`.

## Сборка EXE

[GitHub Actions — Windows portable build](https://github.com/Aspksa/Miyora/actions/workflows/windows-portable.yml). После успешного workflow скачайте артефакт `Miyora-Windows-Portable`, распакуйте ZIP и запустите `Miyora.exe`. Наличие готового артефакта зависит от успешности сборки.

## Разработка

```bash
python main.py
python -m unittest discover -s tests -v
```

API: `GET /api/health`, `GET /api/db/health`, `GET /api/notes`, `POST /api/notes`, `DELETE /api/notes/{id}`.

## Правила развития

- HTTP-маршруты и жизненный цикл сервера — `app/server.py`.
- База данных и миграции — `app/core/database.py`.
- HTML/CSS/JS — `web/`.
- Тесты — `tests/`.
- Запуск Windows — `start.bat` и `launcher.ps1`.
- Данные пользователя и Python runtime не коммитить.

## Проверка стабильности

Запустите `start.bat --doctor` из командной строки Windows. Команда проверяет структуру, импорты, SQLite и права записи и выводит JSON с результатами. Обычный запуск автоматически выполняет предварительную проверку перед запуском HTTP-сервера. GitHub Actions запускает настоящий `start.bat --doctor` дважды из каталога с кириллицей, пробелами и скобками: первый запуск загружает Python, второй повторно использует его. Тесты HTTP API выполняются отдельно командой `python -m unittest discover -s tests -v`.

## SQLite Database Core

Существующие таблицы и записи сохраняются. При первом запуске новая миграция добавляет `notes.deleted_at` и индекс. Удаление заметки теперь мягкое: запись остаётся в базе и может быть восстановлена.

Доступны API: `GET /api/db/stats`, `POST /api/db/backup`, `GET /api/notes?search=...`, `GET /api/notes?deleted=1`, `PUT /api/notes/{id}`, `POST /api/notes/{id}/restore`. Существующие маршруты сохранены. Веб-интерфейс поддерживает заметки, поиск, корзину, статистику и создание резервной копии.

Резервные копии хранятся в `data/backups/` и создаются штатным SQLite Backup API, включая содержимое WAL. Для программного восстановления предусмотрена `app.core.database.restore_backup(path)`; **вызывать только при полностью остановленной Miyora**, предварительно сохранив данные. Восстановление намеренно не доступно через HTTP API.

Проверки: `python -m unittest discover -s tests -v`.
