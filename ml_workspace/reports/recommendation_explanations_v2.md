# Recommendation explanations v2

Date: 2026-10-28. Branch: `ml-model`.

## Why v1 was unhelpful

The popover was connected to real `EstimateItem` data, but it repeated the product name, price, package count, line cost and alternatives. Its reason list came from `why()` labels such as “основной товар” and “известна фасовка”. More importantly, `add_why()` rescored the selected product as a one-product candidate set, so comparative price evidence was lost. It did not expose the decision evidence to the client.

## Actual decision path and evidence

`POST /api/v1/estimate` → `BaselineEngine._item()` → `CatalogRepo.candidates()` → `ContextRanker.score()` → selected `EstimateItem` → `add_why()` → API response → `recommendationPopover()`.

Hard eligibility is material binding, compatible work type (or a confirmed compatible legacy binding), confidence ≥ 0.7 for unconfirmed automatic bindings, active/price/stock repository checks, and required moisture flags for the materials in `NEEDS_MOISTURE`. Tile names receive an additional floor/wall ordering hint. The ranker uses calculability, confirmed binding, stock, catalog recommendation, catalog rating, room-name match, comparable unit price, and applicable verified signals (moisture, washing, wear, slip, frost, fungus, emissions and IP protection). Classification probability is not presented as product quality.

The backward-compatible `EstimateItem` extension is:

- `recommendation_explanation`: deterministic Russian text;
- `recommendation_evidence`: status, selected product ID, room, work, surface, material and typed facts;
- each fact records a code, user-facing label, source (`request`, `binding`, `catalog`, `ranking`, or `user`), optional source value and actual score contribution.

The generator uses only those facts. Missing product-specific metadata produces `limited`, not an invented technical claim. User picks are explicitly described as user choices and are never called ranker winners. Price is mentioned only when a multi-candidate score actually contains a positive price contribution. Surface compatibility is stated only for the existing tile name rule. Bathroom context alone never creates a moisture claim.

## Frontend

The existing `!` interaction and styling remain. Its heading is now **«Почему выбран этот товар?»** and its primary content is the deterministic explanation (or a provider formulation of the same evidence). Price, quantity, line total, product-name duplication and alternatives were removed from this view. An honest insufficient-evidence message is rendered when evidence is absent, and limited catalog evidence is labeled as such.

## GigaChat boundary

The optional provider now receives the same serialized `recommendation_evidence` plus the deterministic fallback. Legacy `selection_signals` and `deterministic_reasons` keys remain temporarily for compatibility. GigaChat may formulate text only; it cannot filter candidates, select a product, alter scores, quantities or prices. API failure leaves the deterministic explanation intact. No live GigaChat call was made.

## Real catalog audit

Read-only database: `/tmp/iym_zero_final.sqlite`, derived from the 88,790-product catalog and its temporary bindings. Requests used the real `/api/v1/estimate` endpoint with explanations disabled externally, so all text below is deterministic. Twenty returned estimate lines were inspected; representative results follow.

| Room / work | Selected real product | Verified evidence used | Generated explanation result |
|---|---|---|---|
| Bathroom / waterproofing | PLITONIT Гидроэласт, ID 381 | material/work binding; relative unit price | Role and binding; no unsupported moisture-property claim |
| Bathroom / drywall | KNAUF влагостойкий, ID 3740 | `влагостойкость: да`; price | Explicit verified moisture statement |
| Bathroom / putty | TIKKIVALA Euro Filler, ID 65883 | moisture text in product name/description; price | Moisture statement with catalog source |
| Bathroom / primer | БИРСMIX, ID 34970 | moisture and antifungal text; price | Both applicable ranker signals |
| Bathroom / floor tile | CULTO Uno, ID 31653 | floor name hint; moisture signal; wear characteristic `4`; price | Surface, moisture and wear evidence (limited to the first two concise facts) |
| Bathroom / wall tile | GLOBAL TILE Aroma, ID 31673 | wall name hint; moisture signal; price | Surface and moisture evidence |
| Bathroom / tile adhesive | VETONIT Granit Fix, ID 3059 | work binding; antifungal signal; price | Only those supported criteria |
| Bathroom / grout | UNIS U-50, ID 624 | work binding; antifungal signal; price | Only those supported criteria |
| Bathroom / socket | BYLECTRICA 16A IP44, ID 67437 | characteristic `степень защиты: ip44`; price | Verified IP44 statement |
| Bathroom / switch | LEGRAND Valena Life IP44, ID 78282 | IP44 in product text; price | Verified IP44 statement |
| Bathroom / light | Эмера 7Вт, ID 15001 | characteristic `степень защиты ip: 44`; price | Verified IP44 statement |
| Bathroom / cable | ВВГп-нгА LS, ID 65225 | work binding; price | Limited; no invented bathroom suitability |
| Bathroom / cable channel | ЭРА 20×10, ID 46904 | work binding; price | Limited |
| Bathroom / electrical component | LEGRAND DIN, ID 58679 | work/material binding only | Limited; the potentially questionable binding is exposed, not embellished |
| Bathroom / pipe | ПНД ПЭ100, ID 32343 | work binding; price | Limited |
| Bathroom / profile | профиль 28×27, ID 4998 | work binding; price | Limited |
| Bathroom / lamp | ОНЛАЙТ GX53, ID 28792 | work binding; price | Limited; no IP claim |
| Bathroom / plumbing | SWEDBE Mars, ID 47852 | work binding; price | Limited |
| Bathroom / floor adhesive | VETONIT Granit Fix, ID 3059 | same evidence as above | No unsupported floor/moisture claim |
| Bathroom / wall grout | UNIS U-50, ID 624 | same evidence as above | No unsupported wall/moisture claim |

The cited product `Основит СТАРПЛИКС AC11`, ID 90657, has catalog description evidence that it is intended for wall/floor tiling, but that field does not currently influence the ranker. Therefore the explanation deliberately does **not** claim it caused automatic selection. In a request with ID 90657 in `picks`, the evidence says it was selected by the user, explains the tile-adhesive role, and does not claim superiority, moisture resistance, or special adhesive compatibility.

## Before / after

**Основит СТАРПЛИКС AC11**

- Before: product name, 520 ₽, one package, 520 ₽ total, alternatives, “основной товар”, “фасовка посчитана точно”.
- After: “Материал «Плиточный клей» нужен для работы «Облицовка плиткой»; товар прошёл привязку к этой позиции. Дополнительных характеристик, подтверждающих преимущество именно этого товара, в каталоге нет. Это пользовательский выбор, поэтому система не утверждает, что он лучше альтернатив.”

**KNAUF влагостойкий гипсокартон**

- Before: repeated price/package data and generic moisture/packaging bullets.
- After: role in drywall installation, verified `влагостойкость: да`, and only ranker-used comparison factors.

**BYLECTRICA IP44 socket**

- Before: repeated estimate facts and “защита от брызг”.
- After: explains the electrical-fittings role and ties the protection statement to the catalog’s actual `IP44` characteristic.

**ОНЛАЙТ GX53 lamp (missing protection metadata)**

- Before: generic recommendation language.
- After: limited role/work explanation; no bathroom/IP/moisture claim is invented.

## Tests

Command:

```fish
uv run --with-requirements requirements.txt --with pytest pytest -q
```

Result: **148 passed, 1 skipped, 7 warnings** in 70.53 seconds. The focused frontend/recommendation/ranker/hybrid group passed **24/24**. Tests cover API-to-popover mapping, honest empty state, exact product association, absence of redundant price/package/alternative content, real estimate response evidence, hybrid explanation payload compatibility, ranker signals and unchanged estimate arithmetic.

The real FastAPI integration was exercised against the full temporary catalog. No browser executable was available, so actual mouse interaction and screenshot capture remain unverified; JavaScript syntax and the popover renderer were executed under Node by the frontend tests.

## Files changed

- `app/schemas.py`: structured evidence response models and fields.
- `app/api/picker.py`: full-candidate evidence construction, deterministic generator and shared provider payload.
- `app/static/index.html`: explanation-first popover.
- `tests/test_frontend.py`: new UI contract and redundancy regression.
- `tests/test_recommendation_flow.py`: real API evidence/product association assertions.
- this report.

## Limitations

- Many catalog records lack normalized intended-application/surface properties. Their text may exist in descriptions but is not claimed as a selection reason unless the current ranker/filter uses it.
- The material/work binding quality itself is upstream data. The evidence layer makes questionable bindings visible but does not change taxonomy, predictions or selection.
- No score-to-score “better than alternative X” sentence is generated. Current evidence supports factor contribution, not a stable causal comparison after all tie-breakers and user picks.
- Browser interaction and live GigaChat remain unverified. Deterministic explanations work without either.
