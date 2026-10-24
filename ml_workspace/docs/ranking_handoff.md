# Ranking model handoff

## Architecture and current flow

RepairCalc is a FastAPI application. Catalog loaders write `Product`, characteristics, and
`ProductBinding` records. Classification suggests/stores material, work types, rooms, flags and
confidence. The estimate engine chooses a room renovation plan, asks `CatalogRepo.candidates()` for
compatible bound products, then calls the configured ranker. Thus repository filtering selects
candidates; classification supplies persisted bindings; ranking orders the already-filtered list.

Canonical runtime interfaces are `app/ml/interface.py`, `app/ml/baseline.py`, `app/models.py`,
`app/schemas.py`, `app/catalog/repository.py`, and `app/engine/baseline.py`. A separate research
prototype exists in `ml_workspace/recommendation/ranker.py`; it is not wired into the backend.

## Exact implemented ranking contract

```python
rank(candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> list[Product]
```

Each candidate has a product identifier and metadata including name, prices, stock, ratings,
categories, normalized specs and raw source data. Its binding has material, zero or more work types,
zero or more room types, boolean flags, source, confidence and confirmation status. `RoomInput`
contains room type, dimensions, optional name/humidity, and optional requested work types.

The current `RatingRanker` sorts all candidates by: in-stock first, confirmed binding first,
descending `recsys_rating`, descending catalog `rating`, then ascending `result_price`. It returns
products only, has no relevance score, and is stable for equal keys. Missing rating is treated as
zero and missing price as zero. The ranker does not filter room compatibility or work compatibility.

Filtering happens earlier in `CatalogRepo.candidates`: material is required; an optional work type
can be required but the current engine does not pass it; required binding flags and minimum binding
confidence are applied; out-of-stock and missing-price records are excluded by default. The engine
currently passes material, required moisture flag when applicable, and confidence 0.8. It then calls
the ranker once per material with one room. For tile only, the engine re-sorts the returned products
using a surface-name hint. Empty input returns `[]`, and the engine emits a missing-product reason.

Classification may attach several work types, but the ranker receives no explicit classification
object and no explicit single/multiple work-type argument. Missing metadata is tolerated by the
baseline sort. This description is implemented behavior, not a desired redesign.

## Integration contract for a future ranker

A replacement must implement the same method and return the same candidate products in desired
order. It must not add/remove products unless backend owners explicitly change the contract; hard
compatibility belongs to `CatalogRepo.candidates()` today. It should:

- handle `[]` as `[]`;
- use `Product.id` as identity and avoid duplicates;
- tolerate missing ratings, price, stock, specs, categories and binding confidence;
- be deterministic for ties;
- avoid mutating products/bindings/room;
- keep output compatible with `EstimateItem.product` and `alternatives` (`ProductBrief`).

Scores are not supported by the runtime return type. If relevance scores are proposed, introduce a
typed result and coordinate an engine/schema migration; do not overload binding confidence. Binding
confidence measures classifier certainty, while a ranking relevance score would measure contextual
suitability. Likewise, passing explicit work type(s), surface, material role, budget, style or user
preferences requires a coordinated contract change. They may be useful proposals but are not
currently available ranker arguments.

The standalone prototype demonstrates one possible typed fixture (`Candidate`, `RankedCandidate`)
with compatibility filters, room/property context, quality/applicability scores, budget constraints
and top-k. It is research code, not the canonical backend contract and must not be swapped in without
an adapter and agreement on ownership of filtering.

## Local setup

```bash
git clone <repository-url> IYM
cd IYM
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q tests
python run_local.py
```

For classifier/research dependencies also run
`pip install -r ml_workspace/requirements-ml.lock.txt`. The saved classifier was produced with
Python 3.13.15; use Python 3.13 for joblib compatibility. Backend defaults to SQLite and loads
`data/catalog.json`/XML if separately supplied, otherwise the local 27-product mock catalog.

Relevant locations:

- `app/ml/interface.py`, `app/ml/baseline.py`: production classifier/ranker protocols and baselines;
- `app/config.py`, `app/api/deps.py`: implementation selection and process-level caching;
- `app/engine/baseline.py`: ranking caller and response construction;
- `app/catalog/repository.py`: candidate selection;
- `app/models.py`, `app/schemas.py`: available persistent and HTTP fields;
- `ml_workspace/recommendation/ranker.py`: independent prototype;
- `ml_workspace/tests/test_ranking.py`: prototype tests;
- `mock_catalog/`: local test catalog;
- `ml_workspace/data/`: local training-derived files (may be ignored/unavailable elsewhere);
- `ml_workspace/artifacts/models/`: local saved artifacts (large files must not be committed).

Run ranking independently with
`pytest -q ml_workspace/tests/test_ranking.py`. Run backend ranker behavior through
`pytest -q tests/test_ingest_and_api.py`. To integrate a future ranker, implement a zero-argument
class matching `Ranker`, set `RC_RANKER_IMPL=package.module:Class`, and verify estimates and empty/
missing-data cases. Do not modify `RatingRanker`; keep it as fallback.

## Outstanding questions

Backend/frontend owners need to decide whether future ranking may filter candidates, whether the
engine should pass the current work type and surface explicitly, whether multiple classified work
types should be ranking features, how room-type bindings are enforced, whether out-of-stock options
may appear, what business meaning a relevance score has, and whether scores should be public API
fields. Data owners must identify a ranking target and evaluation set; current catalog ratings and
`recsys_rating` are features, not an agreed ground-truth objective. Access to the full catalog,
production behavior data, or external services is not included in this repository and must be
arranged separately.
