# TF-IDF classifier integration

## Status and artifact

The selected `splits_v3` artifact is at
`ml_workspace/data/experiments_v3/tfidf_logreg/model/`. It contains:

- `estimators.joblib`: estimators for domain, activity, product category, work type, and room type;
- `preprocessor.joblib`: fitted TF-IDF vectorizer;
- `metadata.json`: format version 2, feature schema, class order, taxonomy and training config;
- `thresholds.json`: per-class thresholds for every multi-label task;
- `dependency_versions.json`: serialization environment;
- validation/evaluation metrics (reporting only).

`load_model()` now rejects missing core files, a format/taxonomy mismatch, missing tasks,
taxonomy-v2 work-type drift, missing thresholds, and missing estimators. Joblib artifacts must only
be loaded with `trusted=True` when their provenance is trusted; joblib/pickle can execute code.

The recorded environment is Python 3.13.15, NumPy 2.1.3, pandas 2.2.3, scikit-learn 1.6.1 and
joblib 1.6.0. Use `ml_workspace/requirements-ml.lock.txt`. A test load on Python 3.14.4 and
scikit-learn 1.9.1 succeeded, but emitted `InconsistentVersionWarning`; that newer environment is
not a supported deployment environment even though the sampled predictions ran.

## Model input and feature availability

Canonical input is `ml_workspace.ml_api.ProductInput`. Name is required. The model's approved
training schema also includes source category, all category names, cleaned description, marketing
description, important/technical attributes, brand, sale unit, price, characteristic count and an
information-completeness value. TF-IDF consumes the textual subset: name, categories, descriptions,
attributes and brand. Price/unit/completeness are retained in the artifact feature schema but are
not consumed by this TF-IDF vectorizer.

The backend `Product` provides name, category mapping, description, brand, price and unit. The
adapter also reads original characteristics from `Product.raw` (`characteristics` for JSON or
`params` for YML), falling back to normalized `specs`. A distinct marketing description is only
available for JSON records that retain `raw.marketing_description`. Missing optional fields become
empty fields; no content is fabricated. Admin endpoints classify catalog records already in the
database; there is no product-creation request schema in the current API. If a future admin UI sends
only a name, inference is technically supported but is **not validated as equivalent to full-feature
inference**.

```python
from pathlib import Path
from ml_workspace.ml_api import ProductInput, load_model, predict

model = load_model(Path("ml_workspace/data/experiments_v3/tfidf_logreg/model"),
                   "taxonomy_v2", trusted=True)
result = predict(model, [ProductInput(product_id=1, name="Кабель ВВГнг 3x2.5")])
```

`predict` accepts one object or a sequence. `Prediction.work_types` is a list, `scores` contains all
work-type probabilities, and each selected label satisfies its own saved threshold. No top-one
reduction is applied.

## Backend selection and compatibility

The public `Suggestion` response contract is unchanged. `get_classifier()` is cached, so the model
loads once per process. Default remains the keyword baseline.

```bash
export RC_ML_CLASSIFIER_BACKEND=trained
export RC_ML_CLASSIFIER_ARTIFACT_PATH=ml_workspace/data/experiments_v3/tfidf_logreg/model
python run_local.py
```

Set `RC_ML_CLASSIFIER_BACKEND=baseline` (or omit it) for `KeywordClassifier`. The legacy `tfidf`
backend value remains an alias for `trained`, and the older `RC_CLASSIFIER_IMPL` extension point
still applies to baseline/custom implementations.

Taxonomy-v2 and backend enums differ. Exact work IDs are preserved. `plumbing_fixture_install` maps
to `plumbing_install`. `floor_covering_install` maps to `laminate_laying` or `linoleum_laying` only
when product text disambiguates it. Unsupported work labels are not silently lost: the unchanged
schema exposes `flags["unsupported_work_type__<id>"] = true`. Unsupported room labels use the same
pattern. Supported room aliases include `living_room -> living`. Product categories map to a backend
material only where an unambiguous enum exists; otherwise material is `other`. Per-label confidence
is in `work_scores`; top mapped work confidence remains `confidence`.

## Actual validation sample

Run in the available (version-mismatched) local environment on 2026-10-22:

| Input | Status/domain | Selected work types (score / threshold) |
|---|---|---|
| Primer for walls | predicted/renovation | none; `priming` 0.1862 / 0.50 |
| Laminate oak 8 mm | predicted/renovation | `floor_covering_install` 0.7809 / 0.40 |
| VVGng cable 3x2.5 | predicted/renovation | `electrical_wiring` 0.7992 / 0.65 |
| Bathroom faucet | predicted/renovation | `plumbing_fixture_install` 0.9821 / 0.65 |
| Cat food | non_renovation | none |
| Universal installation kit (name only) | predicted/renovation | none |
| Paint-primer for walls | predicted/renovation | none; `wall_painting` 0.2366 / 0.60 |
| Product 79552, radiator-valve key | predicted/renovation | `electrical_wiring` 0.9829 / 0.65 and `plumbing_rough` 0.9486 / 0.35 |

These results validate execution and multi-label representation, not semantic accuracy. The last
row is evidence of a likely false positive. The model metrics themselves measure agreement with
weak labels, as stated in the artifact metadata.

## API and tests

Existing endpoint:

```http
GET /api/v1/admin/products/96617/suggest
```

Response shape (values depend on the catalog record/model):

```json
{"material":"paint","work_types":[],"work_scores":{},"room_types":[],
 "flags":{"ml_unknown":false},"confidence":0.0,"model":"tfidf-logreg-taxonomy-v2"}
```

Run `pytest -q tests/test_tfidf_classifier.py`. Artifact-dependent tests skip when the real artifact
is absent; they never generate fake weights. Run all backend tests with `pytest -q tests`.

Known limitations: exact-version validation still needs a Python 3.13 environment; category-to-
material compatibility is intentionally conservative; unsupported taxonomy-v2 values cannot enter
strict enum lists and are signaled in boolean flags; confidence is zero when no supported work type
crosses threshold, even if domain/category confidence is high.
