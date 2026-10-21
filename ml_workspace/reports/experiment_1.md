# Experiment 1 — TF-IDF + Logistic Regression

Реализованы word 1–2 gram TF‑IDF, One-vs-Rest Logistic Regression с `class_weight=balanced`, fixed hash splits по нормализованной карточке, validation threshold selection, joblib save/load и per-class metrics.

Запуск pilot:

```bash
.venv-sandbox/bin/python ml_workspace/experiments/experiment_1_tfidf.py --allow-weak-labels
```

Технический результат: micro-F1 **0.9930**, macro-F1 **0.9709**, precision **0.9919**, recall **0.9941**; train/val/test = 10761/2290/2201.

Это agreement с теми же эвристическими weak labels, которые выводятся из текста. Высокий результат ожидаем и не является валидной оценкой accuracy. Организаторский micro-F1 вычисляется по всем `(product,label)` решениям на независимо вручную размеченном, не использованном для threshold selection test set: `2TP/(2TP+FP+FN)`. Только тогда можно сравнивать с 0.8. Macro-F1 — среднее F1 классов.
