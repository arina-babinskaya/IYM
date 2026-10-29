# Admin full-catalog ML matching integration

Date: 2026-10-29

## Problem and separation

The admin page previously presented renovation `ProductBinding` coverage and called
`POST /api/v1/admin/autobind` as its primary “ML matching” action. That endpoint correctly uses the
renovation classifier, but its material/work/room taxonomy cannot categorize the complete Maxidom
assortment. Products such as seeds, tableware, garden tools, and furniture were therefore shown as
outside the renovation domain even though the independent catalog model can categorize them.

The application now exposes the systems explicitly:

- **Catalog categories (primary admin workflow):** the cached
  `CatalogMatchingClassifier`/`CatalogPredictor`, the 90 trainable leaves of
  `catalog-taxonomy-v2`, and independent `CatalogCategoryAssignment` records.
- **Renovation work bindings (ranking only):** the existing renovation classifier,
  `ProductBinding`, `CatalogRepo.candidates()`, and the unchanged recommendation/ranking pipeline;
  this is not exposed as the admin ML-binding action.

No catalog category is translated into a renovation material or work type. No ranking module reads
the new assignment table.

## Read-only assignment audit

The local 88,790-product database was opened in SQLite `mode=ro` before this correction. It contains
exactly 88,790 assignment rows for 88,790 active products and zero active unassigned products.
`product_id` is unique (zero duplicate groups), all 90 distinct category IDs are valid trainable
taxonomy leaves, and every row uses model `catalog-tfidf-logreg-v1` with taxonomy
`catalog-taxonomy-v2`. Sources are 88,790 `ml`; statuses are 85,120 `predicted` and 3,670
`needs_review`. Every row has three stored alternatives. No assignment or production-like catalog
record was changed during this audit.

## Admin behavior

The correction restores the original single admin layout. Its sole primary action is
**Привязать (ML)**. It starts the full-catalog background job and shows total,
processed, categorized, inserted, updated, unchanged, manually preserved, needs-review, error, and
elapsed-time counters.

The table supports:

- saved category ID and Russian name;
- score, model version, status, and top-three alternatives;
- the original Без привязки, ML, Подтверждённые, and Все filters;
- name, SKU, catalog code, or exact product-ID search;
- confirming the predicted category or selecting a correction from the real taxonomy endpoint.

The backward-compatible renovation `/admin/autobind` endpoint remains available to scripts and API
clients, but it is not linked from the admin interface.

## API

Existing read-only single-product inference remains:

- `GET /api/v1/admin/products/{product_id}/catalog-match`

New catalog-admin endpoints:

- `GET /api/v1/admin/catalog/taxonomy` — taxonomy version and 90 trainable leaves, grouped with
  parent IDs/names; the non-model `review.unresolved` sentinel is excluded from assignment choices.
- `GET /api/v1/admin/catalog/stats` — total, assigned, model suggestions, manually confirmed,
  needs review, unassigned, and coverage.
- `GET /api/v1/admin/catalog/products` — assignment/category/status/search filters and pagination.
- `PUT /api/v1/admin/catalog/products/{product_id}/category` — confirm or correct a category.
- `POST /api/v1/admin/catalog/categorize` — start or join the catalog background job.
- `GET /api/v1/admin/catalog/categorize/status` — poll progress and terminal results.

The catalog bulk job never calls GigaChat, `get_classifier()`, renovation publication rules,
ranking, or `ProductBinding` persistence.

## Persistence

`catalog_category_assignments` is created additively by the project's existing `Base.metadata.create_all`
startup mechanism. It has one row per product (primary key and cascading product foreign key) and
indexed category, taxonomy-version, status, and source columns:

- `category_id`
- `model_score` (nullable for a manual-only assignment)
- `model_version`
- `taxonomy_version`
- `status`: `predicted`, `needs_review`, `confirmed`, or `corrected`
- `source`: `ml` or `manual`
- JSON top-three alternatives
- creation/update timestamps

Automated reruns insert missing assignments, update changed automatic predictions, and count
identical predictions as unchanged. A `source=manual` assignment is always preserved. Confirming
the current predicted category produces `confirmed`; selecting another category produces
`corrected`. Model score/alternatives are retained as review provenance and are not presented as a
human accuracy guarantee.

The artifact review threshold (~0.19155) is used only by the trained predictor to mark
`needs_review`. Its scores are uncalibrated Logistic Regression probabilities and the threshold is
not treated as proof of correctness or as a reason to leave a product uncategorized.

## Bulk processing

The job checks indexed assignment coverage for every active product, then keyset-pages only products
without an assignment and performs name-only batch inference through the long-lived cached
classifier. When coverage is already complete, no model inference or writes occur. CPU inference
runs off the async server loop. Each batch is committed separately, so it does not hold a
catalog-wide transaction. Empty names and isolated inference failures are counted while other
products continue. If a batch inference call fails, the job falls back to per-product calls for
that batch to identify the failing record.

Repeated starts within one application process return the active job. Repeated completed runs are
idempotent and preserve manual decisions. No development or test run started this job against the
88,790-product database.

## Statistics

Catalog coverage is calculated solely from `catalog_category_assignments`. The former 26%
renovation-binding coverage is no longer presented in the admin as catalog categorization coverage.

## Ranking isolation

The following remain unchanged and do not import the catalog matcher or assignment model:

- `app/ml/ranker.py`
- `app/ml/baseline.py`
- `app/catalog/repository.py` candidate selection
- `ProductBinding`
- renovation confidence/publication policy
- estimate and recommendation engines

Regression tests verify that catalog categorization creates no `ProductBinding`, manual catalog
corrections leave an existing binding byte-for-byte unchanged, and the ranked candidate IDs before
and after catalog review are identical. Existing tests also verify ranking loads when the catalog
artifact path is missing and that the catalog adapter does not expose renovation fields.

## Tests

Write-enabled tests use temporary SQLite databases and fixture classifiers. They cover:

- loading exactly 90 trainable taxonomy categories;
- non-renovation seed and garden-tool categorization;
- top-three persistence and API output;
- background progress, partial invalid-product handling, and failure state;
- active-job reuse and repeated-run idempotency;
- accurate catalog statistics and filters;
- manual confirmation, correction, and preservation on rerun;
- artifact failure reporting;
- product ID/category/review search filters;
- frontend endpoint/label compatibility;
- no catalog-job writes to `ProductBinding` and unchanged ranking candidates;
- continued operation of the existing renovation autobind and recommendation fixtures.

The focused catalog/ranking regression selection passed 18 tests. The complete repository run
passed 215 tests and retained two pre-existing failures in `tests/test_frontend.py`: that file
expects recommendation-popover source strings which were already absent from the checked admin
template before this integration. The failures are unrelated to catalog matching or ranking output.

## Running from the admin

1. Start the application normally so the additive table is created (or deploy the equivalent DDL
   first when `RC_AUTO_CREATE_TABLES=false`).
2. Open **Админка**; the ML filter is selected by default so existing assignments are visible.
3. Click **Привязать (ML)** to categorize only products that do not yet have assignments.
4. Confirm correct predictions or use **Изменить** to select a correction from the 90-category taxonomy.

## Limitations

Job coordination/status is process-local. A multi-worker deployment needs a database/advisory lock
and durable job record for global overlap protection and status history. The model evaluation is
weak-label agreement, not human-verified accuracy. The admin currently shows the first 100 rows for
a filter rather than pagination controls, although the API supports offset pagination.
