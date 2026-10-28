# Real backend recommendation hints

Date: 2026-10-28

## Root cause

The `!` control is rendered by `productCell()` in `app/static/index.html`. Its click handler previously
displayed only `EstimateItem.why` as a short bullet list under the fixed heading “Почему выбран этот
товар”. Those strings come from `app/api/picker.py:why()` and are derived from actual positive
`ContextRanker` signal parts; they were not fetched from a mock endpoint. However, the popover
discarded the rest of the real recommendation already returned by the estimate API—selected
product, work/material role, price, calculated packages/cost, ranked alternatives, and optional
explanation—so the generic labels looked like placeholder content.

No separate customer recommendation/explanation endpoint is required for the current UI. The admin
`/api/v1/admin/products/{id}/suggest` endpoint is classification-only and is not used.

## Data flow

1. The calculator sends room/work choices to `POST /api/v1/estimate`.
2. `BaselineEngine` expands work choices into materials and retrieves compatible bound products.
3. `ContextRanker` selects products and orders alternatives.
4. `add_why()` attaches deterministic criteria computed from the selected product's real ranker
   signal parts.
5. The response contains, per `EstimateItem`, `product`, `work_type`, `material`, `title`, quantities,
   `unit_price`, `cost`, `why`, up to three `alternatives`, and optional `reason`.
6. The frontend keeps that response in `currentEstimateData` and now passes the exact room/item-index
   object to `recommendationPopover()`.

No additional API request, persistence, or duplicate recommendation calculation is introduced.

## New popover contents

The existing `!` interaction and visual design are preserved. It now shows only data in the actual
estimate response:

- selected product name;
- associated work and material role;
- catalog product price and unit, when present;
- calculated package count and line cost, when present;
- deterministic backend criteria, when present;
- actual ranked alternative names and prices, when present;
- optional `reason`, including a real configured explanation if the backend supplied one.

If criteria are absent it says: “Для этой рекомендации подробное объяснение пока недоступно.” If
alternatives are absent it states that no other variants were found. Nothing fabricated is used as
a fallback.

The icon is available for every selected product, including limited-metadata results. It is mapped
by room and item index rather than by material/surface, preventing the wrong recommendation from
opening when similar estimate slots exist.

## Stale, loading, empty, and failure behavior

- The existing estimate loading indicator remains.
- Each estimate request receives a monotonically increasing version. A late response from an older
  room configuration cannot overwrite the newer estimate or its hints.
- API failures replace the estimate area with an explicit “Не удалось загрузить рекомендации”
  error and do not fabricate fallback recommendations.
- Re-rendering an estimate replaces all old hint DOM and state.
- Clicking the open icon again closes it; opening another hint closes the previous one; clicking
  outside closes all popovers.

## Files changed for this task

- `app/static/index.html`
- `tests/test_frontend.py`
- `tests/test_recommendation_flow.py` (new)

No backend schema, ranking logic, classifier, taxonomy, model artifact, or database was changed for
this recommendation-hint task.

## Verification

The integration test loads the real sample catalog into an isolated SQLite database, performs real
backend autobinding, requests a multi-product estimate, and verifies that the selected product and
every alternative match catalog rows and prices. A second request with changed room dimensions
produces changed quantities/packages.

The frontend test executes `recommendationPopover()` with Node and covers:

- selected product/work/price/packages/cost;
- multiple alternatives, including an alternative with missing price;
- limited metadata;
- missing criteria and missing alternatives;
- stale-response guard;
- API failure text;
- popover open/close wiring;
- complete inline JavaScript syntax.

Focused command:

```text
.venv-sandbox/bin/pytest -q tests/test_frontend.py tests/test_recommendation_flow.py \
  tests/test_ingest_and_api.py::test_api_flow \
  tests/test_ingest_and_api.py::test_estimate_options_why_and_picks tests/test_hybrid_e2e.py
```

Result: **7 passed**.

Full command:

```text
.venv-sandbox/bin/pytest -q
```

Result: **148 passed, 1 skipped, 37 warnings in 72.85 seconds**. The skip remains the absent optional
taxonomy reference module. Warnings are the previously documented scikit-learn artifact/runtime
version mismatch in the audit environment and a TestClient deprecation.

## Full-catalog backend observation

Against the existing temporary full-catalog validation database, a real cosmetic-bedroom response
returned three selected products and a 3,601 RUB estimate. For example, the wallpaper recommendation
was product 19118 at 269 RUB, 8 rolls / 2,152 RUB, with three real alternatives (product IDs 7565,
21165, and 17206). The popover consumes those exact response fields.

No real GigaChat call was made. If GigaChat explanations are enabled later, the existing backend
writes the validated explanation to `item.reason`; the same popover displays it without making the
frontend dependent on GigaChat.

No browser executable was available in the audit environment, so click-level browser verification
and screenshots are not claimed. The actual served template, Node-executed mapping, and real
backend response were verified.

## Local verification (macOS, Fish)

```fish
cd /Users/arinababinskaya/Documents/GitHub/IYM
source .venv/bin/activate.fish
set -gx RC_GIGACHAT_ENABLED false
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If the local catalog has no bindings, stop the server and follow the safe preview/apply procedure:

```fish
python -m scripts.backfill_bindings
python -m scripts.backfill_bindings --apply --batch 5000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the UI:

```fish
open http://127.0.0.1:8000/
```

Choose `Спальня`, dimensions 4 × 3 × 2.7 m, cosmetic renovation, and keep the default priming and
wallpapering choices. Generate the estimate and click `!` beside each selected product. Confirm:

1. the product name in the popover exactly matches its estimate row;
2. price, package count, and line cost match the row/API response;
3. alternatives are real product names/prices;
4. changing the room dimensions and recalculating updates package counts and the popover;
5. clicking the icon again or outside closes the popover;
6. disabling the backend/network shows an explicit load error, not fabricated hints.

Use browser developer tools to inspect the single `POST /api/v1/estimate` request. Opening `!`
must not create another network request.

## Known limitations

- `EstimateItem` does not include full product characteristics/specifications. They are available
  via the product detail endpoint and option endpoint, but this task deliberately avoids an extra
  request per popover. The UI displays only facts already returned with the estimate.
- Deterministic `why` values are criteria labels derived from ranker signals, not natural-language
  causal explanations or quality probabilities.
- A real LLM explanation is displayed only when the optional backend supplies `item.reason`.
- Browser interaction remains to be checked locally using the instructions above.
