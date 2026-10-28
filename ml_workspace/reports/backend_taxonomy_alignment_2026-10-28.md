# Backend alignment with authoritative ML taxonomy

This is a read-only evaluation of all 88,790 active catalog products. No binding was written and no
GigaChat request was made. The operating threshold is configurable and now defaults to 0.7; model
scores were not changed or reinterpreted as probabilities.

## Outcome

| Measurement | Products |
|---|---:|
| Original baseline at 0.8 | 8,396 |
| Previous integration result at 0.8 | 12,039 |
| Expanded authoritative taxonomy at 0.8 | 16,912 |
| Final category bindings at 0.6 | 28,814 |
| Of which resolve to specific estimate materials | 19,595 |
| Category-only/broad bindings, excluded from estimate material slots | 9,219 |

The distinction in the last two rows is important. Tools, consumables, generic adhesives,
insulation and `other_renovation_material` are now preserved as their actual ML category instead of
being discarded or forced into an unrelated material. They do not automatically enter an estimate
line unless the adapter resolves a specific material that the estimate plan requests.

Exact outcomes sum to the full catalog:

| Outcome | Count |
|---|---:|
| Eligible at 0.6 | 28,814 |
| Below 0.6 | 26,792 |
| Non-renovation | 21,689 |
| Furnishing, not a renovation estimate product | 7,294 |
| Unknown/uncertain domain | 3,854 |
| Material/work taxonomy conflict | 347 |

## Category diagnostic

`Material` values separated by `/` are deterministic specializations within the original ML
category. The eligible/below/conflict/non-renovation/furnishing/unknown columns are mutually
exclusive.

| ML category | Total | Backend material(s) | Eligible | <0.6 | Conflict | Non-renov. | Furnishing | Unknown |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| adhesive | 503 | adhesive/mounting_adhesive/wallpaper_glue/sealant/tile_adhesive | 398 | 90 | 0 | 5 | 3 | 7 |
| beds | 79 | other | 0 | 0 | 0 | 0 | 73 | 6 |
| cabinets_wardrobes | 3,742 | other | 0 | 11 | 0 | 25 | 3,662 | 44 |
| construction_mix | 117 | construction_mix | 98 | 17 | 0 | 2 | 0 | 0 |
| consumables | 148 | consumables | 142 | 5 | 0 | 1 | 0 | 0 |
| countertops | 371 | other | 0 | 1 | 0 | 0 | 369 | 1 |
| decorative_materials | 1,016 | decorative | 860 | 147 | 0 | 6 | 0 | 3 |
| decorative_objects | 407 | other | 0 | 0 | 0 | 0 | 407 | 0 |
| decorative_panels | 604 | decorative | 541 | 56 | 0 | 0 | 3 | 4 |
| doors_windows | 2,125 | doors/door_hardware | 1,695 | 401 | 0 | 0 | 2 | 27 |
| drywall | 145 | drywall/profile | 136 | 9 | 0 | 0 | 0 | 0 |
| electrical_goods | 3,465 | electrical_goods/cable/socket/switch/installation_accessories/cable_channel | 2,569 | 565 | 304 | 26 | 0 | 1 |
| fasteners | 2,686 | fasteners | 2,249 | 436 | 0 | 0 | 0 | 1 |
| floor_covering | 1,044 | floor_covering/laminate/linoleum/underlay | 970 | 71 | 0 | 2 | 0 | 1 |
| hand_tools | 2,136 | hand_tools | 1,204 | 746 | 0 | 157 | 0 | 29 |
| heating_climate | 640 | heating | 598 | 41 | 0 | 1 | 0 | 0 |
| installation_accessories | 556 | installation_accessories/profile/foam/boxes/adhesive | 418 | 135 | 0 | 2 | 0 | 1 |
| insulation | 228 | insulation | 163 | 65 | 0 | 0 | 0 | 0 |
| interior_accessories | 1,061 | other | 0 | 8 | 0 | 3 | 1,015 | 35 |
| lighting | 5,389 | lighting/lamps | 4,485 | 894 | 3 | 7 | 0 | 0 |
| lumber_sheet_material | 246 | lumber_sheet_material | 187 | 26 | 0 | 3 | 14 | 16 |
| mirrors | 293 | other | 0 | 0 | 0 | 0 | 293 | 0 |
| other_renovation_material | 50,327 | other (category retained) | 4,129 | 21,388 | 0 | 21,288 | 38 | 3,484 |
| paint | 1,434 | paint | 1,288 | 134 | 0 | 5 | 0 | 7 |
| plaster | 32 | plaster | 25 | 7 | 0 | 0 | 0 | 0 |
| plumbing | 3,351 | plumbing/pipes | 2,458 | 771 | 40 | 73 | 0 | 9 |
| power_tools | 435 | power_tools | 341 | 94 | 0 | 0 | 0 | 0 |
| primer | 128 | primer | 76 | 52 | 0 | 0 | 0 | 0 |
| protective_equipment | 416 | protective_equipment | 312 | 51 | 0 | 28 | 0 | 25 |
| putty | 80 | putty | 71 | 9 | 0 | 0 | 0 | 0 |
| sealant | 220 | sealant/mounting_foam | 210 | 10 | 0 | 0 | 0 | 0 |
| seating | 589 | other | 0 | 0 | 0 | 3 | 545 | 41 |
| shelving_storage | 773 | other | 0 | 27 | 0 | 47 | 606 | 93 |
| tables | 287 | other | 0 | 0 | 0 | 5 | 264 | 18 |
| tile | 2,100 | tile/grout/tile_adhesive | 1,832 | 267 | 0 | 0 | 0 | 1 |
| tool_accessories | 1,043 | tool_accessories | 831 | 212 | 0 | 0 | 0 | 0 |
| ventilation | 535 | ventilation | 496 | 39 | 0 | 0 | 0 | 0 |
| waterproofing_material | 39 | waterproofing | 32 | 7 | 0 | 0 | 0 | 0 |

All 20 authoritative ML work types are represented by the backend. Eligible binding work-label
coverage is: lighting 4,507; electrical fittings 1,886; tiling 1,837; wall painting 1,780; doors/
windows 1,710; plumbing rough 1,441; decorative finish 1,429; wallpapering 1,321; plumbing fixtures
1,270; floor covering 704; electrical wiring 622; heating/climate 598; ventilation 496; drywall 179;
wall putty 75; priming 75; plastering 34; waterproofing 32; screed 20; demolition 1. A binding may
have multiple work labels, so these counts do not sum to product count.

## Correctness review

Category-scoped specialization prevents cross-category substring errors found during review:

- nylon `стяжка кабельная` remains `construction_mix`; it is no longer turned into electrical cable;
- a door handle “на розетке” remains broad `other_renovation_material`; it is not an electrical socket;
- electrical frames and terminals are `installation_accessories`, not switches or cable;
- drywall profiles, tile grout, lamps and plumbing pipes specialize only inside compatible ML categories.

Representative newly accepted correct examples include a 0.709 electrical switch, 0.661 tile
grout, 0.636 LED lamp, 0.746 laminate, 0.779 ventilation grille and 0.651 thermostat head.
High-risk 0.6–0.8 examples also remain: an aluminium square tube predicted as plumbing, metal-rust
paint assigned `wall_painting`, a bath mat predicted as adhesive, and a biocide predicted as
protective equipment. These are classifier/weak-label errors rather than integration losses and
should be emphasized in the required manual gold review. The repository still has no completed
reviewed gold sample, so no defensible manual precision percentage is claimed.

## Backend and migration

The authoritative `ProductCategory` enum exactly matches all 38 artifact classes. `Suggestion`,
`BindingIn/Out`, the taxonomy API and `ProductBinding` now preserve `product_category`. `Material`
is the downstream specialization used by candidate retrieval and estimates. Broad/tool materials
are not in default work plans, preventing them from contaminating estimate candidates.

`init_db()` performs one additive, idempotent migration:

```sql
ALTER TABLE product_bindings ADD COLUMN product_category VARCHAR(64);
```

It does not update or delete existing rows. Historical and manually confirmed bindings remain
unchanged; their new field is null until an explicit review/regeneration process populates it.

## Validation

- Full suite: **121 passed, 1 skipped**.
- Real catalog inference: 88,790 rows, read-only.
- No classifier retraining.
- No production binding writes.
- No GigaChat calls or token consumption.
- GigaChat structured validation now uses the same authoritative `ProductCategory`, `Material` and
  `WorkType` enums.
