"""Почему консультант пишет «Слишком много запросов»: лимит проекта из .env или отказ самого GigaChat.

Только читает настройки и журнал .cache/gigachat.sqlite, ничего не меняет и в GigaChat не ходит.
Запуск из корня проекта: python -m scripts.gigachat_usage
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.config import get_settings


def main() -> None:
    s = get_settings()
    print("Файл журнала:", s.gigachat_cache_path)
    if not s.gigachat_cache_path.is_file():
        print("Журнала нет — запросов в GigaChat ещё не было."); return
    db = sqlite3.connect(f"file:{s.gigachat_cache_path}?mode=ro", uri=True)
    used, count = db.execute("select coalesce(sum(total_tokens),0), count(*) from request_log where from_cache=0").fetchone()
    print(f"Проект насчитал: {used} токенов, {count} запросов (за всё время, счётчик не сбрасывается)")

    print("\nЛимиты проекта из .env:")
    blocked = False
    if s.gigachat_token_budget is None:
        print("  RC_GIGACHAT_TOKEN_BUDGET — не задан, лимита по токенам нет")
    else:
        left = s.gigachat_token_budget - used
        print(f"  RC_GIGACHAT_TOKEN_BUDGET={s.gigachat_token_budget}: осталось {left}, "
              f"на один запрос проект требует запас {s.gigachat_token_reservation}")
        blocked |= left < s.gigachat_token_reservation
    if s.gigachat_max_requests is None:
        print("  RC_GIGACHAT_MAX_REQUESTS — не задан, лимита по числу запросов нет")
    else:
        print(f"  RC_GIGACHAT_MAX_REQUESTS={s.gigachat_max_requests}: использовано {count}")
        blocked |= count >= s.gigachat_max_requests

    rows = db.execute("select created_at, kind, error_kind, error from request_log where error_kind is not null "
                      "order by id desc limit 5").fetchall()
    print("\nПоследние ошибки от GigaChat:" if rows else "\nОшибок от GigaChat в журнале нет.")
    for at, kind, error_kind, error in rows:
        print(f"  {datetime.fromtimestamp(at):%d.%m %H:%M}  {kind}: {error_kind} ({error})")

    print("\nВывод:")
    if blocked:
        print("  Исчерпан лимит ПРОЕКТА из .env. В GigaChat запрос даже не уходит, токены в Сбере тут ни при чём.\n"
              "  Это настройка Арины — решите вместе, поднять ли лимит или начать счётчик заново.")
    elif rows and rows[0][2] == "rate_limit":
        print("  Отказывает сам GigaChat (HTTP 429): слишком часто или лимит ключа в личном кабинете Сбера.")
    else:
        print("  Лимиты проекта не исчерпаны. Пришлите вывод этой команды — посмотрим дальше.")


if __name__ == "__main__":
    main()
