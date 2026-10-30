# Renovation binding fixes (no retraining)

Date: 2026-10-29

## Outcome

The original renovation adapter now uses exact object evidence for standalone flooring underlay,
electrical installation boxes, circuit breakers, serpyanka, and floor skirting. It no longer treats
an incidental phrase such as `плитка SPC ... с подложкой` as the identity of the product. No model
was retrained and the confidence threshold remains 0.7.

The independent full-catalog classifier, its 90-category taxonomy, artifact, admin endpoints/UI,
and `catalog_category_assignments` were not changed. Ranking code and weights were not changed.

## Confirmed root causes and exact rules

The renovation model intentionally predicts broad categories. The adapter previously searched
`подложк` anywhere in the combined product name/category, so attached underlay on SPC flooring won
over the product head noun. Other narrow materials were category-gated behind broad model output,
and genuine objects either remained unbound or retained wrong broad bindings. Insert-only autobind
could not repair already persisted errors.

`app/ml/tfidf.py` now applies the following narrow rules before general category hints:

- SPC/quartz-vinyl head nouns are `floor_covering`, never standalone `underlay`.
- Underlay must start with `Подложка`, must not be carpet underlay, and must have a known Maxidom
  flooring-underlay source category plus a flooring-underlay material token.
- An electrical box must start with `подрозетник` or `коробка монтажная/установочная/приборная` and
  come from `Коробки монтажные`. Covers, connectors, plates, and templates do not match.
- A breaker must have a breaker head noun and source category `Автоматы защиты`. Both word orders
  `автоматический выключатель` and `выключатель автоматический` remain supported.
- Serpyanka must start with `серпянка` or `лента стекловолоконная (серпянка)` and come from
  `Сетки малярные, серпянка`; unrelated adhesive/painting tape does not match.
- Floor skirting must have the head noun `плинтус`, a compatible floor-skirting source category,
  and must not be ceiling, countertop, decorative, or an accessory whose head noun is angle,
  connector, or end cap.

Each exact name + source-category rule records `direct_material_evidence` and an
`adapter_rule__...` audit flag, supplies a valid broad renovation category, and uses 0.95 as the
confidence of the deterministic material decision. This is separate from and stronger than the
model's broad-category score; it does not lower the publication boundary. Work types are limited to
existing taxonomy-compatible uses.

## Representative classification corrections

| Product | Before | Simulated result |
|---|---|---|
| 102747 SPC ROYCE Ultima, `с подложкой` | `underlay`, floor work, 0.860134 | `floor_covering`, no invented work, direct rule 0.95 |
| 8126 cork underlay, 10 m², 3 mm | unbound | `floor_covering / underlay / floor_covering_install`, 0.95 |
| 11718 genuine podrozetnik | unbound | `installation_accessories / electrical_boxes`, wiring + fittings, 0.95 |
| 476 IEK automatic breaker | unbound | `electrical_goods / circuit_breakers / electrical_wiring`, 0.95 |
| 4403 Folsen serpyanka 48 mm × 45 m | unbound | `installation_accessories / reinforcing_mesh`, plaster/drywall/putty, 0.95 |
| 1405 PVC floor skirting | unbound | `floor_covering / skirting / floor_covering_install`, 0.95 |
| 17653 MDF floor skirting | `lighting / lighting_install` | `floor_covering / skirting / floor_covering_install`, 0.95 |
| 26561 ceramic floor skirting | `tile / tiling` | `floor_covering / skirting / floor_covering_install`, 0.95 |

## Reconciliation plan

`scripts/reconcile_renovation_bindings.py` is dry-run by default. It scans only products recognized
by the audited direct rules, emits before/after JSON and reasons, preserves every confirmed/manual
binding, and makes no change during planning. The current catalog dry-run proposes **292** changes:

- 262 inserts and 30 updates;
- 27 underlays, 36 electrical boxes, 33 missing breakers, 11 serpyanka products, 168 floor
  skirtings, and 17 SPC flooring corrections/normalizations;
- the SPC set includes the exact 10 erroneous `underlay` rows plus one wrong protective-equipment
  binding and six currently unbound SPC products;
- zero confirmed bindings are overwritten.

Applying to an isolated database and planning again is idempotent: the second plan is empty. Real
database application was not run.

## Candidate pools: real before versus isolated simulated after

“Raw relevant” uses the strict audited object rules, not a loose name substring. “Missing” means no
valid work-eligible target binding. These are coverage counts, not a human precision measurement.

| Material | Raw relevant | Correct before | Valid before | Work-eligible before | Wrong before | Missing before | Correct/valid/eligible after | Missing after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| underlay | 27 | 0 | 0 | 0 | 0 | 27 | 27 / 27 / 27 | 0 |
| electrical_boxes | 36 | 0 | 0 | 0 | 17 | 36 | 36 / 36 / 36 | 0 |
| circuit_breakers | 193 | 160 | 160 | 160 | 0 | 33 | 193 / 193 / 193 | 0 |
| reinforcing_mesh | 11 | 0 | 0 | 0 | 0 | 11 | 11 / 11 / 11 | 0 |
| skirting | 168 | 0 | 0 | 0 | 2 | 168 | 168 / 168 / 168 | 0 |

Representative raw IDs are 8126/16082/16732 (underlay), 5231/6217/11718 (boxes),
149/476/1046 (breakers), 4403/15679/17689 (serpyanka), and 1089/1405/3428 (skirting).

Products outside these strict sets remain deliberately unresolved. Examples include under-screed
sound insulation, carpet anti-slip underlay, skirting accessories, ceiling/countertop mouldings,
box covers/connectors/templates, general mesh/tape, and products whose names/source categories do
not establish identity. They were not forced into bindings.

## 47,300 RUB regression

The deterministic regression creates the historical binding for product 102747 and a 20 m² living
room. Before reconciliation it reproduces exactly:

`20 × 1.05 / 2.16 = 9.72 → 10 packs × 4,730 RUB = 47,300 RUB`.

The dry-run leaves that row unchanged. Applying the plan in the isolated database changes 102747 to
`floor_covering`, inserts real cork underlay 8126, and verifies that the underlay candidate pool is
exactly `[8126]`. The estimate can no longer select 102747 as underlay. No ranking behavior or
substitute price was hardcoded.

## Verification

- Focused classification and reconciliation: 29 passed.
- Candidate/ranking/recommendation/autobind/catalog-admin independence: 43 passed.
- Full repository: **228 passed, 2 failed**.
- The two failures are pre-existing frontend-template assertions in `tests/test_frontend.py` for
  strings absent from the checked admin template. They are also documented in the earlier autobind
  diagnosis and are unrelated to these changes; the UI was not modified.
- The real catalog remained at 88,790 products and 22,972 renovation bindings after dry-run.
- No GigaChat request was made.

Retraining is not necessary for these high-specificity families. It may still be useful later for
broader coverage and removal of deterministic specialization, but requires a reviewed gold set and
is not needed to resolve the confirmed incidents.

## Safe application later

First review a fresh dry-run (this writes only the requested report file):

```bash
python -m scripts.reconcile_renovation_bindings \
  --report renovation-binding-dry-run.json
```

Inspect every proposed `before`, `after`, and `reason`. To apply only after explicit approval, choose
a new backup path; the tool refuses to overwrite an existing backup and creates the backup before
the first binding update:

```bash
python -m scripts.reconcile_renovation_bindings \
  --apply \
  --backup-path backups/repaircalc-before-renovation-bindings.sqlite \
  --report renovation-binding-applied.json
```

Stop the application during the SQLite backup/apply window. Verify candidate counts and the 20 m²
estimate, then rerun dry-run and require `changes: []`. Rollback is recoverable by stopping the
application and restoring the explicitly named SQLite backup. The script never touches products,
model artifacts, taxonomy files, catalog assignments, ranking, or admin UI state.
