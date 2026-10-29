# Full-catalog classifier backend handoff

## Purpose and isolation

The TF-IDF + Logistic Regression artifact assigns exactly one taxonomy-v2 catalog leaf to a
Maxidom product. It is used only by catalog-category ML matching. It does not predict renovation
materials, work types, rooms, flags, or suitability.

The safe integration point is `app.api.deps.get_catalog_matching_classifier()`, which constructs
the long-lived `app.ml.catalog_matching.CatalogMatchingClassifier`. The admin endpoint
`GET /api/v1/admin/products/{product_id}/catalog-match` invokes this adapter and returns an isolated
`CatalogMatchOut`. It performs no database write.

Ranking remains a separate flow:

1. Renovation classification (`get_classifier()` / `KeywordClassifier` or `TfidfClassifier`) may
   create `ProductBinding` records.
2. `CatalogRepo.candidates()` filters those bindings by renovation material, work type, flags and
   confidence.
3. `BaselineEngine` calls `RatingRanker.rank(candidates, room)` or the configured
   `ContextRanker.rank(candidates, room)`.

No ranker, candidate repository, `ProductBinding`, renovation classifier, or recommendation code
imports the catalog classifier. `RC_CATALOG_MATCHING_*` settings are read only by the dedicated
catalog-matching dependency. A missing catalog artifact can make the catalog-match endpoint return
503, but does not prevent ranking from loading or running.

Call-graph audit: `get_classifier().predict()` is used by admin row previews, the single-product
renovation suggestion, autobind, `scripts/evaluate_matching.py`, `scripts/backfill_bindings.py`, and
`scripts/gigachat_fallback.py`; tests also call `KeywordClassifier.predict()` directly. None of
these were rerouted. The sole production `.rank()` call is in `BaselineEngine`, using the object
from `get_ranker()`; tests call rankers directly. `RatingRanker.rank(candidates, room)` retains its
original signature and implementation.

## Artifact installation and verification

The downloaded artifact in this checkout is:

```text
ml_workspace/catalog_matching/data/artifact/
  model.joblib
  metadata.json
  taxonomy.json
  checksums.json
```

The directory is Git-ignored; do not commit the 177 MB model. To use another location:

```bash
export RC_CATALOG_MATCHING_CLASSIFIER_BACKEND=catalog_tfidf
export RC_CATALOG_MATCHING_ARTIFACT_PATH=/absolute/path/to/artifact
```

The default is the path above. Never configure this path as `RC_ML_CLASSIFIER_ARTIFACT_PATH`; that
variable belongs to the independent renovation classifier.

Install the recorded runtime (Python 3.13, scikit-learn 1.6.1, NumPy 2.1.3, SciPy 1.14.1,
joblib 1.6.0) from `ml_workspace/requirements-ml.lock.txt`. `CatalogPredictor` verifies the three
payload SHA-256 hashes, taxonomy version, all local taxonomy IDs, the 90 trainable leaves, input
schema, metadata/model class agreement, and deserialization. The 91st taxonomy leaf,
`review.unresolved`, is a review sentinel and is deliberately not a model class.

## Input and output contract

Training used `feature_mode=name`. Supply only the original product name. Product ID and source
category are provenance; they must not be features. The adapter accepts an ORM `Product`, a
`CatalogMatchInput`, or a mapping with `id`/`product_id` and `name`.

`predict_one(product, top_k=3)` and `predict_batch(products, top_k=3)` return one primary category,
ordered alternatives, uncalibrated scores, model name, taxonomy version, artifact provenance, and
a review hint. Empty names raise `ValueError`. Missing, corrupt, or incompatible artifacts raise an
actionable `CatalogArtifactError`. Construct the adapter once and reuse it; it does not reload per
product.

Scores are Logistic Regression `predict_proba` outputs but have not been calibrated against human
labels. The stored threshold `0.1915502956406927` is diagnostic only and is not a safe approval
boundary for unresolved products.

## Local inference

```bash
python -c "from app.ml.catalog_matching import CatalogMatchingClassifier as C; print(C('ml_workspace/catalog_matching/data/artifact').predict_one({'id':'demo','name':'Ножницы для живой изгороди'}))"
```

Verified output for that literal name is `garden.tools` / `Садовый инструмент`, score
`0.9457479047848886`; alternatives are `stationery.office_school` (`0.00798517837392484`) and
`tools.hand` (`0.002554109815807898`).

## Full-catalog evaluation

Run:

```bash
python -m ml_workspace.catalog_matching.evaluate_full_catalog --batch-size 1024
```

This loads the model once, uses names only, and writes the complete prediction CSV, unresolved
queue, 150-item review sample, per-category metrics, confusion matrix, and JSON summary under
`ml_workspace/catalog_matching/reports/`. Large/generated outputs are Git-ignored. The committed
summary is `full_catalog_model_evaluation_v2.md`.

Weak-label agreement is a pipeline diagnostic, not human-verified accuracy. Training, validation,
held-out test, full-labeled-catalog, and unresolved results must always be reported separately.
Previously unresolved records should remain in manual review until score reliability is evaluated
on human annotations. Prioritize low scores, small top-1/top-2 margins, systematic source families,
and suspicious high-score disagreements; do not fabricate review decisions.
