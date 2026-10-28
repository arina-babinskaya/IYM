# Zero-ruble estimate regression: diagnosis and fix

Date: 2026-10-28  
Branch: `ml-model`  
Status: **fixed and verified against a temporary copy of the full catalog database**

No production/local source database was modified. No model was retrained, no taxonomy was
redesigned, the confidence threshold remains 0.7, and no real GigaChat request was made.

## Root causes

### 1. The configured database had products but zero bindings

The actual `.env` resolves to `sqlite:///./repaircalc_local.sqlite`. Before the fix it contained:

| Measurement | Count |
|---|---:|
| Products | 88,790 |
| Active products | 88,790 |
| Active products with non-null prices | 88,790 |
| Active/priced products not explicitly out of stock | 88,790 |
| Product bindings | **0** |
| Confirmed bindings | 0 |
| Automatic bindings | 0 |

The additive `product_category` migration was already present and the column existed. The problem
was not an empty catalog, missing prices, wrong database URL, GigaChat, ranking, or serialization.
The data disappeared at candidate retrieval because every retrieval query joins
`product_bindings`, and the joined table was empty.

The earlier 23,960 figure represented read-only classifier predictions. It did not mean those
predictions had been persisted.

### 2. `run_local.py` skipped autobinding for any non-empty catalog

`seed()` returned immediately when it found at least one `Product`. A database could therefore be
fully populated with 88,790 products and still have zero bindings forever. This was the exact state
of the configured application database.

`run_local.py` now distinguishes products from bindings. If products exist but bindings are zero,
it performs deterministic TF-IDF autobinding with GigaChat forcibly disabled. Existing databases
with any bindings are not silently regenerated. A separate preview/apply command is available for
explicit backfills.

### 3. Wallpaper had a proven downstream taxonomy translation gap

The trained classifier correctly returned:

- category `other_renovation_material`;
- work type `wallpapering`;
- strong renovation/category confidence;
- product names/categories explicitly containing `обои`.

The adapter translated that combination to `Material.other`, so valid wallpaper could never match
the calculator's required `Material.wallpaper` slot. A category-scoped, direct-evidence mapping for
`обои` now produces `Material.wallpaper`. This is a translation correction, not a change to the
authoritative 38-category model taxonomy.

### 4. `Material.other` predictions were incorrectly publishable

`decide_hybrid()` already rejected `Material.other`, but `publishable()` did not. That inconsistency
allowed unusable broad predictions to be persisted and also prevented them from reaching the
optional GigaChat fallback. `publishable()` now requires a concrete material. On the full catalog,
this excludes 1,147 unusable `Material.other` rows.

### 5. Empty estimates looked successful

The engine already emitted per-material warnings, but the API had no overall completeness status
and the frontend always displayed “Ваша смета готова” and a 0 RUB total. The response now includes:

- `status`: `complete`, `partial`, or `unavailable`;
- `priced_items`;
- `missing_items`;
- an explicit top-level warning for partial/unavailable estimates.

The frontend renders a failure/partial heading and diagnostic instead of treating zero as a valid
completed estimate.

## Data-flow diagnosis

The browser workflow itself was correct:

1. Room dimensions, renovation type, default work checkboxes, surfaces, and materials were sent in
   the expected JSON schema.
2. `/api/v1/works` returned the expected renovation plan.
3. The engine expanded works into 3 cosmetic-bedroom material lines and 27 bathroom lines.
4. Before backfill, `CatalogRepo.candidates()` returned zero for every line because its mandatory
   binding join had no rows.
5. Ranking received empty lists, every item received `packages=0`, and subtotals summed to zero.
6. The frontend parsed the response correctly but mislabeled it as a completed estimate.

After backfill, the same request path reaches real catalog candidates, ranking, package calculation,
serialization, and frontend rendering.

## Safe database initialization and compatibility

A new command was added:

```text
python -m scripts.backfill_bindings          # read-only preview
python -m scripts.backfill_bindings --apply  # persist missing TF-IDF bindings only
```

Properties:

- GigaChat is never invoked by this command.
- Default threshold comes from configuration and remains 0.7.
- Only unbound products are classified.
- Repository inserts use conflict-do-nothing.
- Confirmed/manual/historical bindings cannot be overwritten.
- `run_local.py` invokes the same safe ML-only path only when the binding table is completely empty.
- Catalog ingest is also deterministic ML-only; live GigaChat remains an explicit endpoint/pilot
  behavior rather than an accidental ingest side effect.

Legacy manually confirmed bindings with an empty historical `work_types` array are now eligible for
a requested work only when `works_for_material(material)` explicitly confirms compatibility.
Unconfirmed category/material-only bindings remain excluded from specific estimate slots. Safety
checks were not disabled globally.

Candidate retrieval now also excludes non-positive prices rather than merely non-null prices.

## Database state before and after

Validation used `/tmp/iym_zero_final.sqlite`, copied from the configured zero-binding database.
The original `repaircalc_local.sqlite` remains unchanged.

| Measurement | Before | Temporary DB after safe backfill |
|---|---:|---:|
| Products | 88,790 | 88,790 |
| Bindings | 0 | **22,813** |
| Bindings with work types | 0 | **17,533** |
| `Material.other` bindings | 0 | **0** |
| Unbound products | 88,790 | 65,977 |
| Confirmed/manual rows overwritten | 0 | 0 |

Backfill took approximately 20 seconds in the available environment. The audit runtime used
scikit-learn 1.9.1 and emitted compatibility warnings for an artifact trained with 1.6.1. The
project requirements correctly pin 1.6.1; the demo should use that pinned environment.

## Representative candidate counts after the fix

Counts require material, exact compatible work type, active product, positive price, stock not
explicitly false, and confirmed binding or confidence at least 0.7.

| Estimate slot | Candidates |
|---|---:|
| Wallpaper / wallpapering | 1,075 |
| Tile / tiling | 1,522 |
| Paint / wall painting | 1,227 |
| Lighting / lighting installation | 3,517 |
| Plumbing / plumbing fixture installation | 740 |

## Before and after scenarios

### Scenario A: cosmetic bedroom

Input: bedroom, 4 × 3 × 2.7 m, cosmetic renovation, default priming and wallpapering work.

| Result | Before | After |
|---|---:|---:|
| Estimate lines | 3 | 3 |
| Selected products | 0 | 3 |
| Priced/calculated lines | 0 | 3 |
| Missing lines | 3 | 0 |
| Status | misleading success | `complete` |
| Total | 0 RUB | **3,601 RUB** |

Selected real catalog products in the validated database:

- product 81338, primer: 499 RUB;
- product 19118, wallpaper: 8 rolls, 2,152 RUB;
- product 74176, wallpaper glue: 950 RUB.

### Scenario B: bathroom capital renovation

Input: bathroom, 2 × 3 × 2.5 m, capital renovation, the browser's 11 default work choices.

| Result | Before | After |
|---|---:|---:|
| Estimate lines | 27 | 27 |
| Selected products | 0 | 20 |
| Priced/calculated lines | 0 | 17 |
| Missing/uncalculable lines | 27 | 10 |
| Status | misleading success | `partial` |
| Total | 0 RUB | **130,844 RUB** |

Moisture filtering remained enabled. The response explicitly lists unavailable or uncalculable
materials. Some real products, such as grout and putty, have a price and binding but lack catalog
consumption/packaging data sufficient for a defensible quantity calculation; the implementation
does not invent consumption rates or prices.

### Scenario C: hybrid classification

`tests/test_hybrid_e2e.py` verifies an uncertain TF-IDF product receives a mocked, schema-valid,
taxonomy-compatible GigaChat classification, is persisted as `source=gigachat`, becomes retrievable
by material/work type, and can be selected in an estimate.

### Scenario D: GigaChat unavailable

Mocked transport/outage tests verify the failure is isolated. Existing TF-IDF/manual bindings and
estimate generation continue. Backfill, startup recovery, and estimate generation do not depend on
GigaChat.

### Scenario E: no bindings/unsupported selection

The API now returns `status=unavailable`, `priced_items=0`, `missing_items>0`, total 0, and an
explicit diagnostic. The frontend displays “Смету не удалось рассчитать” rather than “Ваша смета
готова”.

## Files changed for this fix

- `app/api/routes.py`: explicit `use_gigachat` control for autobind callers.
- `app/catalog/repository.py`: positive-price filter and safe confirmed-legacy work compatibility.
- `app/engine/baseline.py`: completeness accounting and explicit unavailable/partial diagnostics.
- `app/ml/tfidf.py`: wallpaper translation and concrete-material publication requirement.
- `app/schemas.py`: estimate completeness fields.
- `app/static/index.html`: distinct complete, partial, and unavailable rendering.
- `run_local.py`: recover a populated but completely unbound local database using TF-IDF only.
- `scripts/ingest.py`: prevent implicit GigaChat calls during ingest.
- `scripts/backfill_bindings.py`: safe preview/apply procedure.
- `README.md`: binding initialization instructions.
- `tests/test_zero_estimate_regression.py`: empty estimate, totals/serialization, legacy compatibility.
- `tests/test_frontend.py`: unavailable-state UI regression assertion and JavaScript parser coverage.
- `tests/test_tfidf_classifier.py`: wallpaper mapping and `Material.other` publication coverage.

Earlier audit changes in the same uncommitted worktree remain preserved and were not reverted.

## Test results

Exact command:

```text
.venv-sandbox/bin/pytest -q
```

Result: **146 passed, 1 skipped, 37 warnings in 72.73 seconds**.

The one skip is the pre-existing optional reference import
`ml_workspace.taxonomy.work_type_materials_v2`, which is absent. Warnings include the audit
environment's scikit-learn 1.9.1 loading the tracked 1.6.1 artifact and one TestClient deprecation.

Additional verification:

- isolated startup recovery: 27 products, 0 bindings → 3 safe bindings, no GigaChat;
- live Uvicorn against the full temporary database: HTTP 200 and complete 3,601 RUB estimate;
- served HTML: 76,672 bytes; inline JavaScript parsed successfully with Node;
- empty frontend state text exists in the actual served template;
- full-catalog source database was not modified;
- no paid/live GigaChat request was made.

No browser executable was available in the environment. Click-level browser behavior is therefore
**not claimed as verified**. API, rendered-template, and JavaScript syntax behavior were verified.

## Exact macOS/Fish demonstration: temporary database

These commands do not modify `repaircalc_local.sqlite`.

### 1. Activate the pinned environment

```fish
cd /Users/arinababinskaya/Documents/GitHub/IYM
source .venv/bin/activate.fish
python -c 'import sklearn; assert sklearn.__version__ == "1.6.1", sklearn.__version__'
```

If `.venv` is unavailable, create it with Python 3.13:

```fish
python3.13 -m venv .venv
source .venv/bin/activate.fish
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Copy and migrate the real catalog database safely

```fish
cp repaircalc_local.sqlite repaircalc_demo.sqlite
set -gx RC_DATABASE_URL sqlite:///./repaircalc_demo.sqlite
set -gx RC_GIGACHAT_ENABLED false
python -c 'from app.db import init_db; init_db(); print("migration complete")'
```

### 3. Preview and apply bindings on the demo copy

```fish
python -m scripts.backfill_bindings --batch 5000
python -m scripts.backfill_bindings --apply --batch 5000
python -m scripts.backfill_bindings --batch 5000
```

The first command is read-only. The apply command never calls GigaChat and never overwrites an
existing binding. The final preview should report zero newly eligible rows for the same artifact and
threshold.

### 4. Verify database counts

```fish
python -c 'from sqlalchemy import func,select; from app.db import get_sessionmaker; from app.models import Product,ProductBinding; s=get_sessionmaker()(); print("products",s.scalar(select(func.count()).select_from(Product))); print("bindings",s.scalar(select(func.count()).select_from(ProductBinding))); s.close()'
```

Expected for the audited catalog/artifact: 88,790 products and approximately 22,813 safe bindings.

### 5. Start the application

```fish
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Alternatively, `python run_local.py` now detects a completely empty binding table and performs the
same TF-IDF-only recovery before opening the browser.

### 6. Open and exercise the calculator

```fish
open http://127.0.0.1:8000/
```

Choose exactly:

1. `Спальня`.
2. Length `4`, width `3`, height `2.7`, windows `1`, doors `1`.
3. `Косметический` renovation.
4. Keep the default priming and wallpapering choices.
5. Add the room and click `Рассчитать смету`.

With the audited catalog snapshot, expect three product rows and approximately 3,601 RUB. Confirm
that product names, package quantities, unit prices, line costs, and total are visible.

For the bathroom scenario choose:

1. `Ванная / санузел`.
2. Length `2`, width `3`, height `2.5`, windows `0`, doors `1`.
3. `Капитальный` renovation.
4. Keep the 11 default work choices.

Expect a meaningful partial estimate (audited snapshot: 17 priced lines and 130,844 RUB) plus an
explicit warning for materials whose product or packaging/consumption data is unavailable.

### 7. Verify the exact cosmetic API response

In another Fish terminal:

```fish
curl -fsS -X POST http://127.0.0.1:8000/api/v1/estimate \
  -H 'content-type: application/json' \
  --data '{"object_type":"apartment","renovation_type":"cosmetic","explain":false,"rooms":[{"room_type":"bedroom","renovation_type":"cosmetic","length_m":4,"width_m":3,"height_m":2.7,"windows":1,"doors":1,"works":[{"work_type":"priming","surface":"wall","materials":["primer"]},{"work_type":"wallpapering","surface":"wall","materials":["wallpaper","wallpaper_glue"]}]}]}' \
  | python -m json.tool
```

Verify `status: complete`, `priced_items: 3`, `missing_items: 0`, non-null products, positive
packages/costs, and a positive total.

### 8. Watch backend logs and verify browser state

The Uvicorn terminal should show HTTP 200 for `/api/v1/works` and `/api/v1/estimate`. In browser
developer tools, confirm no blocking JavaScript error. An unsupported selection must show a partial
or unavailable heading and diagnostic rather than a successful 0 RUB estimate.

## Applying to the original local database only after approval

The audit intentionally did not do this. To update the original local SQLite database later:

```fish
cd /Users/arinababinskaya/Documents/GitHub/IYM
source .venv/bin/activate.fish
cp repaircalc_local.sqlite repaircalc_local.sqlite.before_binding_backfill.bak
set -gx RC_DATABASE_URL sqlite:///./repaircalc_local.sqlite
set -gx RC_GIGACHAT_ENABLED false
python -c 'from app.db import init_db; init_db()'
python -m scripts.backfill_bindings
python -m scripts.backfill_bindings --apply --batch 5000
```

The backup is recoverable and the command preserves all existing/confirmed bindings.

## Remaining risks

- Browser clicks were not automated here; perform the short local browser checklist above.
- The configured original DB still has zero bindings until the owner runs the safe apply command or
  starts the updated `run_local.py`.
- Bathroom coverage is meaningful but partial because several catalog rows lack defensible
  packaging/consumption data. No values were invented.
- Use the pinned scikit-learn 1.6.1 runtime for the demo.
- Real GigaChat provider behavior was not exercised. It remains optional and cannot block estimates.
