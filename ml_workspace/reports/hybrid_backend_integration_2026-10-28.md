# Hybrid ML + GigaChat backend integration

Date: 2026-10-28. No production binding was modified and no live GigaChat request was made.

Task-specific changes are in `app/config.py`, `app/api/routes.py`, `app/catalog/repository.py`,
`app/engine/baseline.py`, `app/ml/hybrid.py`, `app/ml/tfidf.py`, `app/llm/gigachat.py`,
`app/static/index.html`, `scripts/gigachat_fallback.py`, `scripts/ingest.py`, `run_local.py`, the
experiment notebook, `.env.example`, `README.md`, and the GigaChat/TF-IDF/hybrid tests.

## Working backend path

`POST /api/v1/admin/autobind` now runs TF-IDF first at the configured 0.7 threshold. Safe ML
results are persisted. If GigaChat is enabled and configured, only eligible low-confidence,
unknown, or conflicting renovation products are reviewed, sequentially and up to
`RC_GIGACHAT_AUTOBIND_MAX_PRODUCTS` (default 30). Confident non-renovation/furnishing products are
not sent. Only validated, evidence-backed category + material + work results are persisted with
`source=gigachat`; all other outcomes stay unbound for admin review. Existing bindings use
insert-on-conflict-do-nothing and cannot be overwritten by automatic classification.

Estimate retrieval now requires the persisted work type as well as material. Category/material-only
bindings therefore cannot enter a specific estimate slot. Existing filters for active status,
stock, price, room flags, moisture resistance, confidence, and manual confirmation remain active.
GigaChat explanation failures append a warning and do not change or abort the estimate.

## Read-only full-catalog measurement

The trained artifact classified all 88,790 active products in 19.243 seconds on the available CPU
(4,614 products/second). These are coverage counts, not accuracy or precision.

| Threshold | Taxonomy-safe category/material bindings | Catalog coverage |
|---:|---:|---:|
| 0.6 | 28,814 | 32.45% |
| **0.7** | **23,960** | **26.98%** |
| 0.8 | 16,912 | 19.05% |

At 0.7, 16,458 rows have material plus work types and are estimate-ready; 7,502 are
category/material-only. There are 38,069 fallback-eligible unresolved renovation products, 347
taxonomy conflicts, 21,689 confident non-renovation products, and 7,294 furnishing products.
The major rejection groups are: below 0.7 (31,646), non-renovation (21,689), furnishing (7,294),
ML unknown (3,854), and taxonomy conflict (347).

Largest estimate-ready materials are lighting 3,517; tile 1,522; pipes 1,428; doors 1,384;
decorative 1,302; paint 1,227; electrical sockets 800; plumbing 740; installation accessories 614;
and heating 566. Largest work groups are lighting installation 3,862; wall painting 1,694; tiling
1,694; electrical fittings 1,686; door/window installation 1,493; plumbing rough-in 1,387; and
decorative installation 1,327.

## Verification results

- Unit and integration suite: **137 passed, 1 skipped**. GigaChat is mocked.
- Isolated hybrid API scenario: passed using a temporary SQLite database and real products from
  `mock_catalog/sample_catalog.json`.
- Scenario A: confident ML -> binding -> work/material retrieval -> estimate: passed.
- Scenario B: uncertain ML -> mocked valid GigaChat -> `source=gigachat` binding -> estimate: passed.
- Scenario C: invalid structured GigaChat result -> no binding/admin review: passed.
- Scenario D: unavailable GigaChat -> no binding/admin review while ML processing continues: passed.
- Scenario E: multi-position bathroom estimate in the existing API suite: passed.
- Category-only exclusion, confirmed-binding protection, stock/status/price/work filters, moisture
  behavior, ranking signals, and short Russian mocked explanations: passed.
- Experiment notebook: every cell executed offline successfully.
- Local Uvicorn startup: successful. `/api/v1/taxonomy` returned 38 categories and 20 works.
  A real local-catalog bathroom estimate returned HTTP 200, 27 lines, 24 priced lines, and total
  31,344 RUB. One warning represented missing catalog coverage rather than an application failure.
- Live GigaChat: **not run or claimed**.

## Cache and accounting

Classification cache identity includes product ID and bounded product content, taxonomy version,
model, prompt/schema version, and configurable cache namespace. Change
`RC_GIGACHAT_CACHE_NAMESPACE` to rerun the same selected products without deleting historical
cache. The ledger distinguishes OAuth, model discovery, classification, repair, cache hits,
validation status, API failures, attempts, latency, reported input/output/total tokens, and unknown
usage. SSL verification remains enabled and all endpoints share the configured CA bundle.

## macOS / VS Code / Fish reproduction guide

Open this exact directory in VS Code:

```fish
cd /Users/arinababinskaya/Documents/GitHub/IYM
code .
```

Create and activate the environment (Python 3.13 is the recorded artifact environment):

```fish
python3.13 -m venv .venv
source .venv/bin/activate.fish
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-notebook.txt
```

Create local configuration, then edit `.env` in VS Code. Never paste the credential into a shell
command or commit `.env`:

```fish
cp .env.example .env
code .env
```

Relevant local values:

```dotenv
RC_DATABASE_URL=sqlite:///./repaircalc_local.sqlite
RC_ML_CLASSIFIER_BACKEND=trained
RC_AUTOBIND_MIN_CONFIDENCE=0.7
RC_GIGACHAT_ENABLED=false
RC_GIGACHAT_CA_BUNDLE=certs/gigachat_ca_bundle.pem
RC_GIGACHAT_TOKEN_BUDGET=20000
RC_GIGACHAT_AUTOBIND_MAX_PRODUCTS=10
RC_GIGACHAT_CACHE_NAMESPACE=pilot-2026-10-28-v1
```

For a live pilot only, add `RC_GIGACHAT_CREDENTIALS` locally and set enabled true. The CA bundle
must be a valid local PEM chain. Do not set SSL verification false.

Apply the idempotent additive database migration and start the backend:

```fish
python -c 'from app.db import init_db; init_db()'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run offline tests, including the isolated end-to-end demonstration:

```fish
python -m pytest -q
python -m pytest -q tests/test_hybrid_e2e.py -s
```

Preview 5–10 fallback candidates without network, then run a no-write pilot with an explicit new
namespace. Omit `--apply`:

```fish
python -m scripts.gigachat_fallback --limit 10
python -m scripts.gigachat_fallback --limit 10 --use-api --cache-namespace pilot-2026-10-28-v1
```

Generate and inspect an example estimate in another terminal:

```fish
curl -sS -H 'content-type: application/json' \
  -d '{"renovation_type":"capital","rooms":[{"room_type":"bathroom","length_m":2,"width_m":3,"height_m":2.5}]}' \
  http://127.0.0.1:8000/api/v1/estimate | python -m json.tool
```

Inspect results at `/docs`, `/api/v1/admin/products?status=ml`, `/api/v1/admin/products?status=unbound`,
and `/api/v1/admin/stats`. Classification responses and token/latency records are in
`.cache/gigachat.sqlite`; scientific pilot tables are under
`ml_workspace/outputs/gigachat_matching_experiment/`. The notebook is
`ml_workspace/notebooks/gigachat_matching_experiment.ipynb`.

## Remaining risks and untested items

- No live GigaChat call was authorized, so current account/model JSON-schema compatibility and live
  latency were not reverified.
- The 38,069 eligible unresolved rows are not a batch recommendation. The bounded fallback is for
  selected pilots/admin work only.
- Coverage is measured without human ground truth and must not be described as precision.
- The local run used SQLite and no Docker/external PostgreSQL service; PostgreSQL SQL generation is
  covered by the existing repository implementation but was not started end to end here.
- The available test environment uses a newer scikit-learn runtime than the 1.6.1 artifact and emits
  compatibility warnings. The Fish instructions pin the recorded dependencies.
