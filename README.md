# Miyora

Локальное приложение: Python, SQLite, тёмный веб-интерфейс.

## Запуск

Из исходников Windows: запустите `start.bat`.

Без Python: откройте [Windows portable build](https://github.com/Aspksa/Miyora/actions/workflows/windows-portable.yml), скачайте артефакт успешного запуска `Miyora-Windows-Portable`, распакуйте и запустите `Miyora.exe`. Артефакт появится только после успешной сборки GitHub Actions.

## Диагностика

- `data/miyora.log` — журнал ошибок Python.
- `launcher-diagnostic.txt` — диагностика запуска BAT.
- `data/miyora.db` — локальная база SQLite.

В переносимой сборке папка `data` создаётся рядом с `Miyora.exe`. Распаковывайте в папку с правами на запись.

## Проверка

`python -m unittest discover -s tests -v`

API: `GET /api/health`, `GET /api/db/health`, `GET /api/notes`, `POST /api/notes`, `DELETE /api/notes/{id}`.
