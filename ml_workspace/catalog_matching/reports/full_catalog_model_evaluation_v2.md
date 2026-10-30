# Full-catalog model evaluation v2

Run date: 2026-10-29. Artifact: `ml_workspace/catalog_matching/model_v2`. Feature contract:
product name only. Batch size: 1,024.

## Coverage and performance

- Catalog rows: 88,790.
- Successful predictions: 88,790; failures: 0; empty names: 0.
- End-to-end prediction and CSV writing: 8.6675 seconds (10,244.1 products/second).
- 87 batch calls: mean 85.36 ms, p95 91.51 ms, maximum 338.53 ms.
- Observed peak RSS: 1,725,264 KiB (Linux `ru_maxrss`; includes the parsed 262 MB catalog, model,
  sparse features, metrics, and report buffers).
- All 90 trained categories were predicted. The most frequent were `lighting.indoor` (6,101),
  `home.textiles` (3,907), `furniture.kitchen` (3,539), `kitchen.tableware` (3,502), and
  `furniture.home` (3,146). Full counts are in `full_catalog_evaluation_summary_v2.json`.
- Score bins: 0.0–0.1: 1,412; 0.1–0.2: 2,442; 0.2–0.3: 1,841; 0.3–0.4: 1,717;
  0.4–0.5: 1,920; 0.5–0.6: 2,395; 0.6–0.7: 3,618; 0.7–0.8: 6,802;
  0.8–0.9: 15,179; 0.9–1.0: 51,464. These are uncalibrated model scores.

## Weak-label diagnostics

| Partition | Rows | Agreement | Macro-F1 | Weighted-F1 | Top-3 agreement |
|---|---:|---:|---:|---:|---:|
| Training | 55,950 | 0.993691 | 0.994587 | 0.993693 | 0.999625 |
| Validation | 11,968 | 0.981451 | 0.967605 | 0.981426 | 0.995655 |
| Held-out test | 11,953 | 0.979252 | 0.974114 | 0.979217 | 0.994897 |
| Full confidently labeled catalog | 79,871 | 0.989696 | 0.988238 | 0.989702 | 0.998322 |

The held-out values reproduce the artifact metadata. Full-catalog agreement includes training data
and is not an independent generalization estimate. All targets are automatically generated weak
labels, not human-verified ground truth. Unresolved products are excluded from every denominator.
Per-category precision/recall/F1/support and the 90×90 confusion matrix are generated separately.

There were 823 labeled disagreements. Frequent directions were `garden.seeds` → `garden.plants`
(30), `home.decor` → `home.rugs` (18), `furniture.kitchen` → `flooring.accessories` (17),
`electrical.switch_socket` → `kitchen.tableware` (16), and `furniture.home` → `home.storage` (11).
These may reflect model errors, weak-label errors, or genuinely ambiguous product families.

## Previously unresolved products

All 8,919 review-queue products received a valid prediction; none received human confirmation.
Original review reasons were 8,089 unmapped source categories and 830 conflicting source rules.
Frequent predictions were `kitchen.appliances` (531), `tools.hand` (477), `auto.accessories` (451),
`kitchen.tableware` (439), `kitchen.utensils` (428), `furniture.home` (358), and `home.storage`
(328).

Uncertainty is substantial: 3,309 scores fall below the stored 0.19155 threshold, 5,259 below
0.35, and 6,352 below 0.50. Top-1/top-2 margins are below 0.02 for 1,296 products, below 0.05 for
2,409, and below 0.10 for 3,533. Systematically represented unresolved source families include
toilet air fresheners, dish dryers, garden-furniture cushions, liquid fragrances, multi-tool saw
attachments, preserving jars, serving dishes, cooking spoons, euro-slate, and pliers.

The generated 150-product manual-review sample contains 100 close-margin unresolved products,
25 additional lowest-score unresolved products, and 25 suspicious high-score disagreements with
existing weak labels. It contains real catalog rows; no human outcomes are claimed.

Recommended policy: keep every formerly unresolved item reviewable. Sample and annotate by source
family and predicted class, validate score/margin reliability on those annotations, and only then
choose any automation threshold. Do not auto-approve based on `0.19155` or a high score alone.

## Integration and ranking isolation

Catalog matching enters through `get_catalog_matching_classifier()` and
`CatalogMatchingClassifier.predict_one/predict_batch`; the API entry point is
`GET /api/v1/admin/products/{product_id}/catalog-match`. Its DTO has only catalog-category fields.
It does not persist into `ProductBinding`.

The existing renovation classifier dispatcher, `KeywordClassifier`, `TfidfClassifier`,
`CatalogRepo.candidates()`, `RatingRanker`, `ContextRanker`, ranking weights/features, estimate
engine, and recommendation paths were not modified. Static regression tests reject catalog
classifier references in protected ranking/candidate modules, and ranking construction succeeds
when the catalog artifact path is missing.

Focused verification: 51 passed, 0 failed. The earlier full-suite run (before adding the passing
API isolation test) had 204 passed and 2 failed. Both failures are pre-existing frontend-template string assertions in
`tests/test_frontend.py`; no frontend file was changed by this work. All ranking tests passed.

## Limitations and risks

- Labels measure weak-label agreement, not business accuracy.
- The catalog JSON parser loads the source object in memory; observed peak RSS is therefore high.
- Scores are uncalibrated and out-of-domain inputs still receive a top-1 class.
- Generated CSV/JSON reports and the 177 MB model are local, Git-ignored artifacts.
- Manual review has not yet been performed.
