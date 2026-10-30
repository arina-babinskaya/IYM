# Renovation candidate coverage improvements

## Outcome

Candidate selection now uses a strict, tiered fallback: exact material/work binding first, then a documented compatible-work binding, then a material-only binding when the renovation taxonomy explicitly supports that material for the requested work. Tiers are not mixed. Price, active status, stock, confidence, required flags, and manually confirmed binding behavior remain enforced.

The catalog snapshot contains 88,790 products and 23,234 renovation bindings. All database results below come from a SQLite copy. The real database was only opened read-only and was not reconciled by this work.

## Root causes confirmed

1. `CatalogRepo.candidates()` previously required the requested work to occur literally in `ProductBinding.work_types`. This discarded 64 genuine primers bound to `priming` and 1,872 fasteners whose otherwise valid bindings have no work labels.
2. Floor leveling compounds, damper tape, beacon profiles, and tile-leveling systems require object-level specialization. The broad renovation model output stored them as `construction_mix`, `insulation`, `profile`, or another broad material, so work fallback alone could not recover them.
3. Persistence is insert-only. Existing broad/wrong rows cannot be corrected by rerunning autobind, and missing rows need an explicit reconciliation.
4. The ranker was not the cause: it received empty lists. Its implementation and weights were not changed.

## Candidate-selection rules changed

- Exact work binding remains the first and exclusive tier when present.
- A primer bound to `priming` may be a compatible fallback for waterproofing, floor screed, tiling, plastering, puttying, painting, or wallpapering.
- An electrical box bound to wiring/fittings may support lighting installation.
- A material-only row is considered only if it has no persisted work types and `works_for_material()` explicitly supports the requested work. This recovers fasteners without allowing a wrong material into the slot.
- Fallback ranking views retain their original confidence and add audit flags: `candidate_compatible_fallback` or `candidate_material_only_fallback`, plus `candidate_requested_work__<work>`.
- No synthetic confidence is assigned. Exact and fallback tiers are never mixed, so the unchanged ranker cannot promote a fallback above an available exact candidate.

## Narrow material specialization

The original renovation adapter now recognizes these source-constrained objects:

| Family | Required evidence | Result |
|---|---|---|
| Floor screed/leveling mix | Maxidom cement/gypsum floor-leveling category and an anchored product name such as `пол наливной` or `ровнитель` | `screed_mix`, `floor_screed` |
| Damper tape | Anchored `лента демпферная`, `Пенополиэтилен` source category, and NPE/PPE/polyethylene evidence | `damper_tape`, `floor_screed` |
| Screed/plaster beacon | Anchored beacon-profile name and drywall-profile source category | `beacons`, `floor_screed` + `wall_plastering` |
| Tile-leveling system | Tile-leveling source category and explicit clamp/wedge/leveling evidence; floor-leveling beacons excluded | `tile_leveling`, `tiling` |

These deterministic rules use the existing direct-evidence confidence of 0.95 and the existing publication threshold. They do not change or retrain either model.

Representative simulated corrections include:

- 2916 — `пол наливной цементный БОЛАРС 1050 Экспресс 25кг` → `screed_mix`.
- 52778 — `лента демпферная НПЭ с фартуком ...` → `damper_tape`.
- 22429 — `профиль выравнивающий маячок 3000х10...` → `beacons`.
- 1525 — `система для выравнивания плитки ...` → `tile_leveling`.

Negative tests exclude cable ties, furniture dampers, beacon fixtures, and floor-leveling beacons incorrectly filed under tile-leveling.

## Before/after coverage

Counts are uncapped eligible products after normal price/status/stock/confidence checks. The normal repository call still returns at most its requested limit (200 by default).

| Estimate slot | Before | After exact | Compatible | Material-only | Final eligible |
|---|---:|---:|---:|---:|---:|
| Waterproofing / waterproofing | 29 | 29 | 0 | 0 | 29 |
| Waterproofing / primer | 0 | 0 | 64 | 0 | 64 |
| Floor screed / screed mix | 0 | 22 | 0 | 0 | 22 |
| Floor screed / primer | 0 | 0 | 64 | 0 | 64 |
| Floor screed / damper tape | 0 | 1 | 0 | 0 | 1 |
| Floor screed / beacons | 0 | 11 | 0 | 0 | 11 |
| Wall plaster / plaster | 24 | 24 | 0 | 0 | 24 |
| Wall plaster / primer | 9 | 9 | 0 | 0 | 9 |
| Wall plaster / beacons | 0 | 11 | 0 | 0 | 11 |
| Wall plaster / reinforcing mesh | 11 | 11 | 0 | 0 | 11 |
| Priming / primer | 64 | 64 | 0 | 0 | 64 |
| Painting / paint, primer | 1,227 / 7 | 1,227 / 7 | 0 | 0 | 1,227 / 7 |
| Wallpaper / wallpaper, glue, primer | 1,075 / 28 / 5 | 1,075 / 28 / 5 | 0 | 0 | 1,075 / 28 / 5 |
| Tiling / tile, adhesive, grout | 1,520 / 5 / 165 | 1,520 / 5 / 165 | 0 | 0 | 1,520 / 5 / 165 |
| Tiling / primer | 0 | 0 | 64 | 0 | 64 |
| Tiling / leveling system | 0 | 58 | 0 | 0 | 58 |
| Floor covering / laminate, linoleum | 285 / 408 | 285 / 408 | 0 | 0 | 285 / 408 |
| Floor covering / underlay, skirting | 27 / 168 | 27 / 168 | 0 | 0 | 27 / 168 |
| Electrical wiring / cable, channel, boxes, breakers | 281 / 33 / 36 / 194 | same | 0 | 0 | same |
| Electrical fittings / socket, switch, boxes | 800 / 391 / 36 | same | 0 | 0 | same |
| Lighting / lighting, lamps | 3,516 / 331 | same | 0 | 0 | same |
| Lighting / electrical boxes | 0 | 0 | 36 | 0 | 36 |
| Drywall / board, profile, mesh, putty | 14 / 128 / 11 / 25 | 14 / 120 / 11 / 25 | 0 | 0 | same except 8 beacon profiles correctly leave `profile` |
| Doors/windows / doors, foam, hardware | 1,384 / 10 / 99 | same | 0 | 0 | same |
| Plumbing fixtures / plumbing, pipes | 740 / 42 | same | 0 | 0 | same |
| Ventilation / ventilation | 464 | 464 | 0 | 0 | 464 |
| Heating/climate / heating | 566 | 566 | 0 | 0 | 566 |
| Decorative finish / decorative, mounting adhesive | 1,302 / 25 | same | 0 | 0 | same |
| Fasteners in each taxonomy-supported installation slot | 0 | 0 | 0 | 1,872 | 1,872 |

There are no empty material/work combinations in the current estimate taxonomy after simulated reconciliation. Fastener reuse is deliberately broad at the material tier; product choice remains with the unchanged contextual ranker, and this is the principal area to monitor for catalog-quality noise.

## Reconciliation plan

The isolated full-catalog plan contains 92 changes: 68 inserts and 24 updates.

| Material | Proposed changes |
|---|---:|
| `screed_mix` | 22 |
| `damper_tape` | 1 |
| `beacons` | 11 |
| `tile_leveling` | 58 |

The second plan after applying to the isolated copy contains zero changes, confirming idempotency. Confirmed/manual bindings are skipped. The JSON report records product ID, name, action, rule, and complete before/after values.

Safe future procedure, only after explicit approval:

1. Stop application writers and take an additional filesystem/database snapshot.
2. Run the default dry-run from the repository root:
   `PYTHONPATH=. python scripts/reconcile_renovation_bindings.py --report renovation-binding-candidate-coverage-dry-run.json`
3. Review every proposed row, especially any manually curated catalog additions.
4. Apply only with an unused backup path:
   `PYTHONPATH=. python scripts/reconcile_renovation_bindings.py --apply --backup-path backups/repaircalc-before-candidate-coverage.sqlite --report renovation-binding-candidate-coverage-applied.json`
5. Run the dry-run again; it must report zero changes.
6. Rollback, if required, by stopping writers and restoring the backup as the database file. Retain both JSON reports for audit.

No apply command was run against the real database in this work.

## SPC 47,300 RUB regression

The deterministic test recreates product 102747 at 4,730 RUB per 2.16 m² package for a 20 m² room. Before reconciliation, ten packages produce 47,300 RUB. The dry-run itself makes no change; after isolated reconciliation, 102747 is `floor_covering`, cannot enter the `underlay` pool, and a genuine standalone underlay remains eligible. The full-catalog simulation also confirms `SPC_IN_UNDERLAY=False` with 27 genuine underlay candidates.

## Tests

- Focused renovation/backend/admin-independence suites: **88 passed**.
- Full suite: **239 passed, 2 failed**.
- The two failures are existing frontend template-string assertions in `tests/test_frontend.py`; no UI code was changed as required. They are unrelated to classification, binding, candidate selection, reconciliation, ranking, or the independent admin catalog classifier.
- `git diff --check` is clean.

Covered regressions include exact-tier precedence, compatible primer reuse, material-only fasteners, wrong-material rejection, price/status/stock/confidence/flag preservation, direct material recovery, isolated persistence, end-to-end estimate flow, SPC exclusion, ranking compatibility, and independence of the full-catalog classifier/admin matching path.

## Remaining limitations

- The real database will not gain the 92 corrected/new bindings until an approved reconciliation is applied; code fallback alone recovers primers and fasteners but cannot repair wrong material identities.
- A single damper-tape candidate is a genuine but fragile pool. Additional products should only be added with equally strong evidence.
- Material-only fasteners lack subtype/use metadata. They solve empty slots, but future subtype extraction would improve relevance without changing ranker weights.
- Retraining is not required for these confirmed families. It may improve broader catalog recall later, but the narrow adapter rules are sufficient for the observed gaps.

## Architectural verification

Ranking code, weights, budget/quality logic, UI, model artifacts, the 90-category classifier and taxonomy, admin matching, and `catalog_category_assignments` were not modified. Only the original renovation adapter, renovation candidate repository, guarded reconciliation tooling/tests, and reports changed.
