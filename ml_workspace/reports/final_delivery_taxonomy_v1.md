# Итог поставки taxonomy_v1

Реализованы versioned taxonomy, детерминированный weak labeler, master dataset, фиксированные group-aware splits, manifest, class support, leakage allowlist/tests, multi-task API, export/reload, single/batch inference adapter и Colab notebook. Backend и исходный JSON не изменены.

Каталог: 88 790 товаров. Domain: 46 239 renovation, 9 919 confirmed non-renovation, 32 632 unknown. Splits: 62 081 / 13 392 / 13 317. Multi-work rows: 126; conflicts: 2 463. Подробные distributions — `dataset_statistics_v1.json`; сравнение с прошлой версией — `labeling_version_comparison.json`. Рост coverage не интерпретируется как рост accuracy.

Manual-review CSV перед архивированием проверены: 0 заполненных `reviewed_*`/notes, все статусы `unreviewed`. Они находятся в `archive/manual_review_generated`; retired tests/scripts — в `archive/legacy_manual_workflow`. Активный pipeline их не читает.

Изменения для будущего backend: объединены laminate/linoleum works, расширены door/window, переименована финальная сантехника, добавлена декоративная установка; требуется явный mapping к production enum. Модель должна загружаться singleton-adapter, а database write остаётся вне scope.

Нерешённые вопросы: пороги production-неопределённости следует подтвердить на независимой экспертной выборке; категории с малой поддержкой (`plaster`, `demolition`, `floor_screed`, `waterproofing`) требуют независимой проверки; границу встроенной мебели/furnishing нужно согласовать перед расширением scope; sentence-embedding production encoder и версии runtime следует выбрать при развёртывании.

Полномасштабное обучение на всех 88 790 строках не запускалось. Выполнен компактный end-to-end smoke test TF-IDF; его метрики не используются как заявка на качество. Full pytest: 54 passed, 4 warnings. Warnings: одна внешняя deprecation и три constant-label предупреждения из намеренно малой smoke-выборки.
