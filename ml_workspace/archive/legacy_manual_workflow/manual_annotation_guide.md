# Руководство по ручной аннотации

Подготовлены два непересекающихся файла по 200 строк: `manual_review_representative.csv` — случайная catalog sample для оценки реальной частоты ошибок; `manual_review_targeted.csv` — трудные, unknown/other и недопредставленные семейства. Seed: 20261022. Targeted sample не репрезентативна.

## Работа

```python
import pandas as pd
df = pd.read_csv("ml_workspace/data/manual_review_representative.csv", keep_default_na=False)
df[df["work_type_status"] == "unknown_needs_review"]
df[df["proposed_product_categories"].str.contains("unknown")]
```

В VS Code откройте CSV через Data Viewer/Excel extension; readable name/category/description находятся рядом с labels. Исходные характеристики доступны в `products_clean.csv` и `product_characteristics.csv` по `product_id`.

Заполняйте reviewed-поля JSON-массивами. Известная неприменимость work types — `[]`; неизвестная применимость — статус `unknown_applicability` и пояснение, а не подтверждённый пустой set. `other` означает понятный класс вне словаря, `unknown` — нехватку данных. После проверки установите `review_status=reviewed`.

Проверка:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/validate_annotations.py ml_workspace/data/manual_review_representative.csv
.venv-sandbox/bin/python ml_workspace/scripts/explore_labels.py
```

В будущий training pipeline импортируются только строки `review_status=reviewed`; proposed labels не заменяют reviewed labels.
