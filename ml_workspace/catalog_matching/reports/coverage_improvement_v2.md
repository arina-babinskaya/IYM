# Coverage improvement v2

Generated from all 88,790 catalog records on 2026-10-29. Labels remain weak labels, not human-verified ground truth.

## Why v1 left 36,052 records unresolved

V1 used ordered source-name regexes over a flat export. The export supplies exactly one category per product and no parent hierarchy, so hierarchy propagation was impossible. The rules omitted many ordinary source categories, treated any cross-family substring match as a conflict, and lacked major assortment families. Broad substrings also collided: `Фасады - МДФ` matched both building façades and kitchen furniture; electrical frames matched decorative finishing; furniture handles matched door hardware. V1 therefore had 28,620 unmapped and 7,432 ambiguous products.

The complete v2 unresolved population—not a sample—is summarized in `unresolved_source_categories_v2.csv`, sorted by affected products. It contains counts, common name-prefix patterns, representative real examples, candidates, failure reason, and explicitly records that source hierarchy is absent. The largest v1 gaps included MDF façades (2,084), furniture handles (548), switch/socket frames (514), pendant lights (507), wall lights (429), footwear (402), protective coatings (298), protection breakers (274), hosiery (253), and cabinet carcasses (220).

## Taxonomy audit

Existing IDs were retained. Eight trainable leaves were added after the full unresolved audit:

| New leaf | V2 support | Justification |
|---|---:|---|
| `personal_care.hygiene` | 1,352 | Shampoo, oral/body care and hygiene had no semantically valid existing leaf. |
| `apparel.clothing_footwear` | 1,209 | Ordinary footwear/hosiery is distinct from protective workwear. |
| `finishing.painting_tools` | 1,047 | Brushes, rollers and spatulas are neither paint nor general hand tools. |
| `stationery.office_school` | 802 | Notebooks, paper and writing supplies formed a material independent family. |
| `electrical.components` | 755 | Terminals, lamp holders, boxes and connectors are not cables or switchgear. |
| `furniture.components` | 405 | Generic furniture panels/shelves are not complete home or kitchen furniture. |
| `garden.accessories` | 393 | Plant supports, flower stands and garden décor are neither pots nor tools. |
| `plumbing.water_treatment` | 211 | Water filters and cartridges are not pipes or bathroom accessories. |

This raises trainable leaves from 82 to 90; `review.unresolved` remains a non-trainable operational leaf. No category was removed. Definitions were added for new leaves and existing semantics/IDs were not silently changed. A row-by-row audit of every leaf—definition, exclusion, v1/v2 support, siblings, granularity and low-support warning—is in `taxonomy_audit_v2.csv`.

Countertops remain `furniture.kitchen`; kitchen wall panels map to `finishing.decor`; hedge shears map to `garden.tools`; explicitly named flower stands map to `garden.accessories`. These choices are based on actual names/source categories, not the examples alone.

## Mapping precedence and improvements

V2 uses: (1) narrow product-name overrides, (2) reviewed exact source-category ID mappings, (3) ordered source-name semantic rules, and (4) explicit review. Exact mappings preserve source ID/name, method, evidence, rule ID, and confidence in `source_category_mapping_v2.csv`. Broad new-family rules only fill a gap when no pre-existing specialist rule matches.

Product overrides require explicit product-name phrases. Descriptions are retained for inspection but are not allowed to trigger these overrides after an audit found that incidental prose can create false positives. The final dataset contains 26,150 exact-ID labels, 53,286 source-name-rule labels, and 435 product-name overrides.

Largest support gains include kitchen furniture +2,869, indoor lighting +1,446, personal care +1,352, apparel +1,209, home textiles +1,100, painting tools +1,047, furniture hardware +961, kitchen appliances +869, stationery +802, finishing décor +794, electrical components +755, and tool accessories +749.

## Before and after

| Metric | V1 | V2 |
|---|---:|---:|
| Confident | 52,738 | 79,871 |
| Unmapped | 28,620 | 8,089 |
| Ambiguous | 7,432 | 830 |
| Review total | 36,052 | 8,919 |
| Confident coverage | 59.4% | 89.95% |
| Trainable leaves | 82 | 90 |

V2 resolves 27,133 previously unresolved products. Across all records, 27,157 targets changed: 27,133 review leaves became trainable labels and 24 previously confident products moved through explicit countertop/hedge-shear overrides. No previously confident label was invalidated. The complete per-category before/after support is in `coverage_transition_v2.json`.

## Quality review and remaining risk

`label_audit_sample_v2.csv` contains 140 real, deterministic review rows stratified across newly resolved categories, product overrides, formerly ambiguous rows, broad categories, rare categories, confusing neighbors, and remaining review rows. It includes IDs, names, source category, old/new status and target, method, rule and evidence. It is explicitly a review sample, not ground truth.

Automated consistency checks found no multi-label targets, unknown target IDs, invalidated confident labels, duplicate-group leakage, or split ID overlap. The product-override false-positive audit led to name-only, explicit-phrase matching. Semantic precision is still not independently verified because no human annotations were supplied. Exact mappings—especially broad home, décor, hardware and kitchen families—should receive human review before treating weak-label metrics as business accuracy.

The remaining 8,919 review records comprise 8,089 unmapped long-tail products and 830 true rule conflicts. The largest remaining source group has only 30 rows, indicating that high-frequency mapping gaps were addressed. They remain unresolved where no reviewed exact mapping exists or evidence still points to multiple families.

## Splits v2

- Train: 55,950
- Validation: 11,968
- Test: 11,953
- Fixed seed: 20261029
- Grouping: SHA-256 of normalized name with long SKU-like numeric tokens removed
- All 79,871 supervised rows have one target; review rows are excluded from loss/evaluation.
- Product IDs and duplicate groups are isolated across splits; evaluation rows are not oversampled or synthesized.
- Default features remain product name only. Source category, IDs, rule/confidence/status, target and split fields are provenance and never features.

All 90 classes occur in all three splits, but four leaves remain too small for stable per-class evaluation: `building.masonry` has 4/1/1 train/validation/test rows, `electrical.smart_security` 18/4/3, `building.dry_mix` 22/4/4, and `flooring.wood` 23/5/4. No examples were fabricated to improve these counts; their metrics must be interpreted cautiously.

`metadata.json` records checksums, version and taxonomy version; `taxonomy_snapshot.json` freezes `catalog-taxonomy-v2` with the dataset.

## Colab

Copy `data/splits_v2` to the configured Drive data root, open `notebooks/train_catalog_classifier_colab.ipynb`, and leave `SPLIT_VERSION = "splits_v2"`. Configure `REPO_SLUG`, Drive root and Colab Secret `GITHUB_TOKEN`, then run cells in order. The notebook verifies manifest checksums and taxonomy-version compatibility, creates a unique experiment directory, and retains TF-IDF + Logistic Regression with accuracy, macro/weighted F1, per-class metrics, confusion matrix and top-3/top-5 accuracy. No full model was trained during this work.
