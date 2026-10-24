# Experiment 2 — Sentence Embeddings + Logistic Regression

Реализованы configurable sentence encoder, fixed normalized embeddings, `.npy` cache с проверкой product IDs, те же leakage-aware splits/targets, OvR Logistic Regression, thresholds, timing и сохранение classifier/config. Encoder не fine-tune-ится.

```bash
.venv-sandbox/bin/python ml_workspace/experiments/experiment_2_embeddings.py --allow-weak-labels --model-name sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Полный pilot не запущен: `.venv-sandbox` использует Python 3.14, а официальный PyTorch CPU index не предоставил совместимый `torch` wheel (`torch was not found in the package registry`). Обычный resolver начал выбирать многогигабайтную CUDA-сборку и был остановлен. Модельные веса не скачивались. Реализация проверена автоматическим тестом с mocked embeddings; после появления CPU-compatible PyTorch команда станет исполнимой без изменений. Результаты будут agreement с weak labels, пока не появится verified set.
