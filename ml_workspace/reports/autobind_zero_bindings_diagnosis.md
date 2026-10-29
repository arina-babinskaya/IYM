# Autobind zero-bindings diagnosis

Date: 2026-10-29

## Result

The reported zero was mostly a correct idempotent fixed point, but the UI did not expose enough
information to distinguish that from a failed or empty job. The configured renovation classifier
had already published every remaining product that passed its conservative publication policy.
There was also one real adapter bug: names written as `выключатель автоматический` matched the
generic wall-switch hint, while only the reverse word order (`автоматический выключатель`) matched
the circuit-breaker hint. This produced `switch + electrical_wiring`, was correctly marked
taxonomy-inconsistent, and prevented 160 genuine automatic circuit breakers from being published.

The fix recognizes both word orders before the generic switch hint. A read-only rerun predicts 160
new, internally consistent `circuit_breakers + electrical_wiring` candidates. No threshold,
taxonomy, ranking weight, model artifact, or catalog-matching behavior was changed.

## Trace and job status

The browser calls:

1. `POST /api/v1/admin/autobind?background=true&use_gigachat=false`;
2. the application creates one in-process job and opens its own database session;
3. `CatalogRepo.unbound()` keyset-pages active products without a `ProductBinding`;
4. the existing renovation classifier from `get_classifier()` predicts `Suggestion` objects;
5. `publishable()` applies the renovation binding policy;
6. `CatalogRepo.save_ml_bindings()` uses `ON CONFLICT DO NOTHING` and commits each batch;
7. `GET /api/v1/admin/autobind/status` supplies progress until completion;
8. the browser reloads the admin rows and displays the job's actual inserted-row count.

The reported UI message could only have been rendered after the old polling loop left `running`
and received job statistics, so it is consistent with a successfully completed job. There is no
durable job-history table, and the original process's in-memory job object was not available during
this investigation; consequently its exact historical counters cannot be recovered independently.
The current database and a complete read-only replay reproduce why that job returned zero.

Cancellation previously could leave an in-memory job looking `running`, because `CancelledError`
was not converted to a terminal state. Jobs now expose `cancelled`; failed, cancelled, and completed
states all terminate polling with a clear message.

## Read-only production-like database measurements

Database opened with SQLite URI `mode=ro`; no write-enabled autobind was run.

| Measurement | Count |
|---|---:|
| Active products | 88,790 |
| Existing bindings | 22,812 |
| Existing automatic bindings | 22,812 |
| Existing manual bindings | 0 |
| Active unbound products selected by autobind | 65,978 |
| Products processed in read-only replay | 65,978 |
| Publishable candidates before the fix | 0 |
| Rows persisted during diagnosis | 0 |
| Duplicate/database conflicts during diagnosis | not applicable (read-only) |
| Classifier exceptions during diagnosis | 0 |

The configured threshold is **0.7**, not 0.8. It is applied by `app.ml.tfidf.publishable()` to the
adapter's binding/material confidence. On the unbound population, confidence ranged from 0 to
0.9954, averaged 0.3069, and 7,576 predictions were at or above 0.7. Confidence alone is not enough:
the product must also be renovation-domain, known, have a supported product category and material,
and be taxonomy-consistent.

### Exclusive pre-fix rejection reasons

Rules are listed in evaluation order, so every product appears exactly once.

| Reason | Count |
|---|---:|
| Outside the renovation domain | 32,835 |
| Supported renovation prediction but material maps to `other` | 24,194 |
| Below confidence 0.7 | 8,699 |
| Taxonomy-inconsistent material/work mapping | 250 |
| Publishable | 0 |
| **Total** | **65,978** |

Overlapping diagnostic attributes (not additive) were: 58,402 below threshold, 57,007 material
`other`, 59,220 without work types, 32,835 outside the renovation domain, 25,541 without a product
category, 3,854 unknown/uncertain, and 347 taxonomy-inconsistent.

Representative correctly rejected products include:

- product 1, alder smoking chips: outside renovation, no binding evidence;
- product 2, plastic food jar: outside renovation;
- product 16, hand cultivator: predicted broad `other_renovation_material`, maps to unsupported
  `other` and has only 0.2951 confidence;
- product 31, mosquito coils: broad `other`, 0.3107;
- product 3, flexible mixer hose: plausible plumbing binding but only 0.3150 confidence;
- product 6, shower mixer: plausible plumbing binding at 0.6736, below the configured boundary.

These examples demonstrate why coverage should not approach 100%. Seeds, food storage, garden,
furniture, pest-control, and other assortment branches must not receive invented renovation work.

### Post-fix read-only result

The same complete replay after correcting the word-order hint produces exactly **160 publishable
candidates**, all `circuit_breakers + electrical_wiring`. Examples include product 149
(`выключатель автоматический SE CITY9 1P 16А`, confidence 0.7610), product 1046 (DEKRAFT 10A 3P,
0.8155), and product 1653 (LEGRAND TX3, 0.9428).

The remaining 65,818 products are still rejected: 32,835 outside domain, 24,194 unsupported
material, 8,699 below confidence, and 90 remaining taxonomy inconsistencies. They should remain
unbound pending evidence-backed adapter/model improvements or manual review.

## Existing binding audit

All 22,812 existing rows have a product category, a non-`other` material, confidence at least 0.7,
the renovation-domain flag, no taxonomy-inconsistent flag, and an active product. The primary key
on `product_id` prevents duplicate bindings, and automatic persistence never updates an existing
row. Of these bindings, 5,280 are material-only (empty work-type list); they are deliberately not
eligible for a work-specific ranking slot unless the existing candidate rules permit it. This audit
establishes structural/publication-policy usability, not manual semantic correctness of every row.

## Code changes

- `app/ml/tfidf.py`: recognize both automatic-circuit-breaker word orders before generic switches.
- `app/db.py`: return the database's affected-row count from chunked upserts.
- `app/catalog/repository.py`: return the actual inserted binding count after commit.
- `app/schemas.py`: add candidates, inserted bindings, skipped/rejected counts, persistence
  conflicts, rejection reasons, errors, and a cancelled terminal state to `AutobindJob`.
- `app/api/routes.py`: validate classifier batch shape, classify exclusive rejection reasons, count
  actual inserted rows instead of attempted candidates, expose conflicts/provider errors, log batch
  diagnostics, and make cancellation terminal.
- `app/static/index.html`: show status, processed/candidate/inserted/rejected/conflict/error counts,
  elapsed time, translated rejection reasons, and a meaningful zero-result explanation.
- `tests/test_tfidf_classifier.py`: regression for reverse-order automatic circuit-breaker names.
- `tests/test_autobind_jobs.py`: isolated persistence, threshold, irrelevant-product, repeat,
  zero-candidate, malformed-output, progress, failure, UI, and catalog-classifier-independence tests.

## Persistence and UI semantics

`bound` now means rows actually inserted, not candidates passed to an insert-ignore statement.
`candidates` records valid binding candidates; `persistence_conflicts` records candidates ignored by
the uniqueness rule; `rejected` and `rejection_reasons` explain non-candidates. Repeating autobind is
safe: bound products are absent from the next keyset query, and the primary key plus conflict-ignore
protects against races. Batch commits mean an exception preserves completed prior batches and marks
the job failed rather than reporting success.

The “ML” filter remains `confirmed = false`; “Без привязки” remains the absence of a binding. Stats
still count confirmed rows as manual and unconfirmed rows as automatic. The completion counter now
uses the job's inserted count and refreshes the admin list after completion.

## Tests and limitations

Focused regression run: 24 passed, including hybrid/ranking retrieval and the independent
`catalog-match` deployment test. Automated tests use temporary SQLite databases and never call
GigaChat. The controlled fixture proves one valid paint binding is inserted with correct fields,
irrelevant seeds and a 0.69-confidence primer remain unbound, stats increase once, and a repeated
job creates no duplicate.

The full repository suite was also run during this work. It reached 211 passing tests with two
pre-existing frontend-template assertion failures unrelated to autobind (expected recommendation
popover source strings absent from the current checked template). No real database writes, model
retraining, artifact changes, ranking changes, taxonomy expansion, commit, or push were performed.

Job state remains in process memory and overlap protection is per application process. A deployment
with multiple API workers would require a database-backed/advisory job lock and durable job record
for cross-worker exclusion and historical status recovery.
