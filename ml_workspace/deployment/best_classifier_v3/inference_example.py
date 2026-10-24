"""Minimal inference example for the selected local artifact."""
from pathlib import Path

from ml_workspace.ml_api import ProductInput, load_model, predict


ARTIFACT = Path("ml_workspace/data/experiments_v3/tfidf_logreg/model")


def main() -> None:
    model = load_model(ARTIFACT, "taxonomy_v2", trusted=True)
    products = [
        ProductInput(
            product_id=1,
            name="Ламинат дуб 8 мм",
            source_category="Ламинат",
            category_names="Напольные покрытия | Ламинат",
        )
    ]
    for result in predict(model, products):
        print(result)


if __name__ == "__main__":
    main()
