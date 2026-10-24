# Dataset v3 report

## A. Why the split needed updating

The taxonomy-v2 test split was created by hashing each duplicate group into a 70/15/15 bucket. This prevented group leakage, but it did not stratify multi-label targets. As a result, the 41 eligible `waterproofing` products in 27 independent groups were allocated 36/5/0, and the 22 eligible `demolition` products in 13 groups were allocated 21/0/1. Several other rare labels had only 2–14 test positives.

The investigation showed that the split was not the only cause. The full catalog/rule/eligibility audit found:

- `waterproofing`: the 41 explicit waterproofing materials/accessories were correctly detected; no eligible positive was lost to the supervision mask. The zero test support was an allocation failure.
- `demolition`: 22 products were labeled, while one genuine sledgehammer was excluded after the substring `носк` matched incidental description text. Group scarcity is real (13 groups), but still permits all three splits.
- `wall_plastering`: three explicit plaster products were suppressed because their descriptions mentioned a later “decorative plaster” layer, triggering a negative rule over the entire description.
- `floor_screed`: the rule missed explicit retailer categories named “Смеси для выравнивания полов”; meanwhile 31 automotive cargo ties were false positives because `стяжки` is ambiguous. The corrected support is therefore lower but materially cleaner.
- `drywall_install`: drywall sheets/profiles were covered, but 20 putties explicitly intended for drywall joints were missing a valid secondary label.
- `wall_putty`: six automotive body fillers were invalid positives; ten tinted wall putties had a false `plumbing_fixture_install` secondary label caused by a long-span bathroom/acrylic expression.
- `priming`: all 80 products in the explicit primer category were covered, but documented downstream applications were not retained as secondary work labels.
- All 19,223 v2 rows with `work_types_valid=false` had no work-type positives. Eligibility therefore did not remove rare positive work labels except for the one demolition conflict described above. Invalid rows remain available to other target masks but are never treated as work-type supervision.

### Initial v2 diagnostic

“Multi-positive” means a positive product had more than one assigned work type. Product IDs are unique, so eligible support and unique positive products are equal.

| Work type | Eligible support | Unique products | Positive groups | Multi-positive | Train | Validation | Test |
|---|---:|---:|---:|---:|---:|---:|---:|
| demolition | 22 | 22 | 13 | 0 | 21 | 0 | 1 |
| electrical_wiring | 1,305 | 1,305 | 628 | 152 | 926 | 208 | 171 |
| plumbing_rough | 1,590 | 1,590 | 881 | 152 | 1,150 | 226 | 214 |
| ventilation_install | 535 | 535 | 336 | 0 | 378 | 82 | 75 |
| heating_climate_install | 633 | 633 | 271 | 70 | 487 | 78 | 68 |
| waterproofing | 41 | 41 | 27 | 0 | 36 | 5 | 0 |
| floor_screed | 33 | 33 | 22 | 0 | 18 | 10 | 5 |
| wall_plastering | 22 | 22 | 21 | 0 | 14 | 6 | 2 |
| drywall_install | 166 | 166 | 109 | 0 | 126 | 29 | 11 |
| wall_putty | 81 | 81 | 62 | 10 | 54 | 14 | 13 |
| priming | 80 | 80 | 56 | 0 | 54 | 12 | 14 |
| wall_painting | 886 | 886 | 407 | 0 | 595 | 167 | 124 |
| wallpapering | 1,340 | 1,340 | 1,140 | 0 | 928 | 189 | 223 |
| tiling | 1,809 | 1,809 | 1,669 | 0 | 1,245 | 287 | 277 |
| floor_covering_install | 1,933 | 1,933 | 1,605 | 70 | 1,400 | 290 | 243 |
| door_window_install | 879 | 879 | 370 | 0 | 683 | 99 | 97 |
| electrical_fittings | 1,272 | 1,272 | 934 | 0 | 907 | 184 | 181 |
| plumbing_fixture_install | 2,280 | 2,280 | 1,900 | 10 | 1,577 | 344 | 359 |
| lighting_install | 4,318 | 4,318 | 3,346 | 0 | 2,966 | 657 | 695 |
| decorative_finish_install | 1,273 | 1,273 | 849 | 0 | 857 | 198 | 218 |

## B. Coverage before and after

The table combines two effects: evidence-supported weak-label corrections and redistribution of duplicate groups. The full-support changes are described after the table; split-column changes alone must not be interpreted as new labels.

| Work type | v2 train | v2 validation | v2 test | v3 train | v3 validation | v3 test |
|---|---:|---:|---:|---:|---:|---:|
| demolition | 21 | 0 | 1 | 16 | 3 | 4 |
| electrical_wiring | 926 | 208 | 171 | 800 | 172 | 172 |
| plumbing_rough | 1,150 | 226 | 214 | 1,103 | 236 | 236 |
| ventilation_install | 378 | 82 | 75 | 375 | 80 | 80 |
| heating_climate_install | 487 | 78 | 68 | 443 | 95 | 95 |
| waterproofing | 36 | 5 | 0 | 29 | 6 | 6 |
| floor_screed | 18 | 10 | 5 | 17 | 4 | 4 |
| wall_plastering | 14 | 6 | 2 | 23 | 5 | 5 |
| drywall_install | 126 | 29 | 11 | 132 | 27 | 27 |
| wall_putty | 54 | 14 | 13 | 57 | 12 | 11 |
| priming | 54 | 12 | 14 | 58 | 11 | 11 |
| wall_painting | 595 | 167 | 124 | 639 | 135 | 137 |
| wallpapering | 928 | 189 | 223 | 944 | 202 | 202 |
| tiling | 1,245 | 287 | 277 | 1,271 | 272 | 273 |
| floor_covering_install | 1,400 | 290 | 243 | 1,307 | 281 | 280 |
| door_window_install | 683 | 99 | 97 | 615 | 132 | 132 |
| electrical_fittings | 907 | 184 | 181 | 891 | 191 | 190 |
| plumbing_fixture_install | 1,577 | 344 | 359 | 1,589 | 341 | 340 |
| lighting_install | 2,966 | 657 | 695 | 3,024 | 647 | 647 |
| decorative_finish_install | 857 | 198 | 218 | 891 | 191 | 191 |

Full eligible v3 support and independent-group counts are: demolition 23/13; electrical wiring 1,144/513; plumbing rough 1,575/870; ventilation 535/336; heating/climate 633/271; waterproofing 41/27; floor screed 25/25; wall plastering 33/29; drywall 186/125; wall putty 80/60; priming 80/56; wall painting 911/425; wallpapering 1,348/1,145; tiling 1,816/1,675; floor covering 1,868/1,597; doors/windows 879/370; electrical fittings 1,272/934; plumbing fixtures 2,270/1,890; lighting 4,318/3,346; decorative finish 1,273/849.

`waterproofing` did not gain fabricated positives; its 6/6 validation/test coverage is redistribution. `demolition` gained one recovered sledgehammer and was redistributed. `wall_plastering`, `drywall_install`, and several finishing labels gained evidence-supported secondary labels. `floor_screed` fell from 33 to 25 because false automotive positives were removed while 23 real floor-leveling mixtures were recovered.

## C. Weak-label changes

Dataset v3 uses `weak_rules_v3` while preserving the complete `taxonomy_v2` vocabulary and hierarchy.

Additions are gated by a compatible retailer category plus explicit name/description/characteristic evidence. They added: floor screed 23, wall painting 25, drywall installation 20, wall plastering 11, wallpapering 8, tiling 7, floor covering 5, wall putty 5, and demolition 1 label assignments.

Narrow disambiguation removed: electrical wiring 161 (`провод` within `трубопровод/газопровод`), floor covering 70 (heated-floor products merely described as installed under laminate/etc.), floor screed 31 (automotive cargo ties), plumbing rough 15 (gas-pipeline hardware), plumbing fixtures 10 (bathroom/acrylic long-span match), and wall putty 6 (automotive body filler). These are corrections, not quota optimization. In total, 367 products changed work labels; 89 gained labels while retaining all prior labels, 278 lost at least one invalid label, and 61 lost all work labels. Thirty-seven automotive rows moved from renovation to non-renovation; one previously invalid row became valid renovation and one became non-renovation. No taxonomy class was added, renamed, or removed.

Representative changes:

| Product ID | Product | Source category | v2 labels | v3 labels | Evidence / rule |
|---:|---|---|---|---|---|
| 4600 | шпатлевка готовая ТЕКС Профи Финишная 5кг | Шпатлевки готовые | wall_putty | wall_putty, wall_painting, drywall_install | Description explicitly says use under painting and for drywall joints; `v3:documented_use:*`. |
| 12087 | шпатлевка гипсовая ВОЛМА Шов 20кг | Шпатлевки сухие гипсовые | wall_putty | wall_putty, drywall_install | Explicit joint-filling purpose for drywall. |
| 14243 | грунтовка акриловая BITUMAST 5л | Грунтовка | priming | priming, wallpapering | Description explicitly documents preparation under wallpaper. |
| 1743 | мастика WEBER Vetonit tec.822 гидроизоляционная | Гидроизоляция полимерная | waterproofing | waterproofing, tiling | Description says waterproofing under tiled facing. |
| 2916 | пол наливной цементный БОЛАРС 1050 Экспресс | Смеси для выравнивания полов цементные | none | floor_screed, floor_covering_install | Explicit floor-leveling category and use under floor coverings. |
| 56500 | штукатурка цементная 2в1 шпатлевка ремонтная ЦЕРЕЗИТ CT 29 | Штукатурка цементная | wall_plastering | wall_plastering, wall_putty | Both operations occur in the product name; `v3:explicit_dual:plaster_putty`. |
| 6975 | грунт Белокрас глубокого проникновения 10л | Грунтовка | priming | priming, wall_plastering | Description explicitly documents preparation before plastering. |

Ambiguous mentions without a directional use statement remain unchanged. For example, simply listing drywall or tile as a compatible substrate is not enough on its own.

## D. Leakage checks

- Product IDs in more than one split: **0**.
- Duplicate/near-duplicate groups in more than one split: **0**.
- Unique groups: **66,940**.
- Labels outside taxonomy v2: **0**.
- Split generation repeated in-process with identical assignments: **passed**.
- JSON-list serialization and CSV round-trip: **passed**.
- Required columns and files: **passed**.
- Work-type-invalid rows treated as supervised work-type rows: **0**. Task-specific validity masks remain intact for the other targets.

The duplicate signature is unchanged from v2: normalized source category + name + description, with numeric variants replaced and the first 40 tokens hashed. Entire groups are assigned atomically. The new deterministic greedy iterative approximation optimizes row support, positive independent-group support, multi-label support, and repeated label combinations while keeping group isolation absolute.

## E. Multi-label preservation

### Multi-label Coverage Analysis

The v2 implementation already evaluated all work rules independently and appended matches; it did not stop after the first match and did not overwrite prior labels. Coverage was low-quality because secondary evidence found only in descriptions/characteristics contributed 0.55, below the 0.65 threshold, while broad category substrings produced three recurring false combinations.

The assigned-label distributions over eligible products were:

| Labels per product | v2 | v3 |
|---|---:|---:|
| 0 | 49,301 | 49,337 |
| 1 | 20,034 | 20,161 |
| 2 | 232 | 64 |
| 3 | 0 | 7 |
| 4+ | 0 | 0 |

V2 had 232 assigned multi-label rows (0.3335%), distributed 178/27/27. Its only combinations were electrical wiring + plumbing rough (152), floor covering + heating/climate (70), and wall putty + plumbing fixture installation (10). The rule-and-product audit found none suitable for retention under the documented semantics; they were substring/category-context errors rather than verified multi-purpose products. “Zero retained as genuine” is a deterministic evidence audit, not a human gold-standard judgment.

V3 has 71 evidence-supported multi-label products (0.1021%), distributed **52 train / 10 validation / 9 test**. Increasing correctly supported multi-purpose products—not increasing the raw number of assigned labels—was the objective. Sixty-two products changed from one to two-or-more labels; no product changed from zero to multi-label directly.

Common v3 combinations are:

- drywall_install + wall_putty: 14;
- priming + wall_painting: 11;
- wall_painting + wall_putty: 9;
- priming + wall_plastering: 8;
- priming + wallpapering: 7;
- drywall_install + wall_painting + wall_putty: 5;
- floor_covering_install + floor_screed: 4;
- priming + wall_putty: 4;
- floor_screed + tiling: 3;
- tiling + waterproofing: 2.

Rare single-product combinations are drywall + putty + wallpapering, tiling + plastering, plastering + putty, and floor covering + floor screed + tiling. Potentially compatible pairs such as priming + tiling or priming + waterproofing remain absent because the current records/rules did not provide sufficiently precise directional evidence; absence alone was not treated as an error.

Deduplication and eligibility did not disproportionately remove v2 multi-label rows: all 232 were eligible, and their 178/27/27 distribution broadly followed split size. The principal issue was rule precision and missing explicit-secondary-use logic.

## F. Dataset versioning

| Field | Value |
|---|---|
| Dataset version | `dataset_v3` |
| Taxonomy version | `taxonomy_v2` |
| Labeling-rule version | `weak_rules_v3` |
| Split algorithm | deterministic group-aware greedy iterative multi-label stratification |
| Random seed | `20261024` |
| Intended ratio | 70% / 15% / 15% |
| Final rows | 88,790 = 62,153 train / 13,319 validation / 13,318 test |
| Eligible work-type rows | 69,569 |
| Source catalog SHA-256 | `590a500be31d7a8d56e625c231ef978fc1a1a7b6d0a2e65eb33b88d68eee175e` |
| Prepared source SHA-256 | `0c579ce2bbb80a84d5da24f67fdd33c13e0fc38d63d5f00eda6de909d91f45f7` |
| Master SHA-256 | `11555a4d50d53947810a36da53f348d6cee3234ccfb6ff726afa000f5bb63e83` |
| Split manifest SHA-256 | `24dbe51b6b510435e6c978c74775a6752416367589f06ae9fb5bc1c79b9c0640` |
| Train SHA-256 | `4cc7f50feb0ba09c7eabcc88b213efe79bd614f6a0f0213be786d4b75522e82c` |
| Validation SHA-256 | `06802005e3a328e82a6fd46eab87135618e25fbf8e6a9cd1367fb57ff482004f` |
| Test SHA-256 | `68a6f968cfd823c3e4e298cb89113247820b738dba373f0a4ef03c842794498f` |

All checksums are also recorded in `data/splits_v3/dataset_manifest.json`. Generated data is ignored by Git to avoid committing large CSV/JSON files; run `python -m ml_workspace.scripts.build_taxonomy_v3_dataset` to reproduce it from the prepared source.

## G. Known limitations

- These are deterministic weak labels, not independently reviewed ground truth. Future metrics measure agreement with automatic rules and must not be described as real-world classification accuracy.
- Rare support is bounded by independent groups. `demolition` has only 13 groups and `waterproofing` 27; 3/4 and 6/6 validation/test support are improvements but still yield high-variance metrics.
- `floor_screed` has only 25 corrected positives. Its v3 test count is 4 rather than 5 because v2 included automotive false positives; quality was prioritized over nominal support.
- Secondary-use rules deliberately favor precision. More genuine overlap may exist in unstructured descriptions, but ambiguous substrate and compatibility mentions were not promoted automatically.
- Duplicate grouping is deterministic and conservative, but no heuristic can guarantee semantic identity for every catalog card.
- The audit is based on retailer metadata and rule semantics, not human annotation of every changed record.

## Using v3 in the notebook

The Colab notebook now exposes:

```python
SPLIT_VERSION = "splits_v3"
```

It concatenates `train.csv`, `validation.csv`, and `test.csv`, loads `split_manifest.csv`, and passes the same `DatasetBundle` to `prepare_features()`. Change `EXPERIMENT` only among `tfidf_logreg`, `catboost_structured`, and `embeddings_logreg`; all three then consume exactly the same split. No model training was run for this dataset task.
