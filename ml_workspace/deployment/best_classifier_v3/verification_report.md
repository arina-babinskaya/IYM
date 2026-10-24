# Artifact verification report

Verified 2026-10-24 on CPU with Python 3.13.11 and the saved scikit-learn 1.6.1 dependency line.
The artifact loaded without retraining; taxonomy/task mappings and all multi-label thresholds passed
loader validation. Single and batch inference, empty optional fields, repeated-call stability, and
JSON serialization passed. A known test product with two true weak labels retained both predicted
labels. Removing or corrupting required files produces an actionable loader/adapter error.

A clean-room run copied only `ml_workspace.ml_api`, `taxonomy_v2.py`, and the seven artifact files
to a temporary directory. A fresh Python 3.13.11 virtual environment installed only the five pinned
runtime requirements and successfully produced stable single/batch predictions. The isolated tree
contained no catalog, split/training CSV, notebook, Colab/Drive integration, or remote model cache.

Measured locally after warm-up: 0.197 s cold load; 3.78 ms mean single-item inference; 4.11 ms for a
12-item batch (0.343 ms/item); approximately 250 MiB peak process RSS. These are one-machine
measurements, not production SLOs. Full valid test inference (10,168 rows) took 0.083 s in direct
matrix scoring, excluding CSV/text preparation.

Smoke examples correctly exercised renovation, non-renovation, ambiguous, and missing-field paths,
but several obvious products returned no work type (primer, paint, drywall, waterproofing, and a
demolition tool). These examples were not used for tuning and are not an accuracy evaluation.
The nine-row true multi-label test subset produced micro-F1 0.7742, exact match 2/9, seven
underpredictions, and no overpredictions. Overall metrics remain agreement with weak labels only.

Backend verification used `GET /api/v1/admin/products/{product_id}/suggest`. A complete local
putty product returned HTTP 200, `material=putty`, and `work_types=["wall_putty"]`; a name-only
product returned HTTP 200, `material=other`, and an empty work-type list. Both responses retained
the existing schema and model identifier. Focused integration tests passed 17/17; the complete
repository suite passed 89/89. The repository's Python 3.14 test environment emits expected
scikit-learn version warnings; the clean Python 3.13 environment does not.
