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

## Надёжный запускатор

`start.bat` использует `launcher.ps1` из той же папки. Скачивайте оба файла вместе с проектом. Приоритет имеет переносимый `Miyora.exe`, затем проверенный Python >=3.9. Запускатор защищает от двух экземпляров из одной папки системным mutex и сохраняет диагностику в `launcher-diagnostic.txt`. Ошибки не удаляют `data/miyora.db`.

## Переносимый Python

При первом запуске `start.bat` скачивает официальную встраиваемую сборку Python 3.13.9 с python.org в `runtime/python/` рядом с проектом. При последующих запусках использует локальный интерпретатор, не меняя системный Python. Для первого запуска требуется интернет. Скачанная папка `runtime/` не добавляется в Git. Переносите всю папку Miyora вместе с `runtime/` для работы без повторной загрузки.
