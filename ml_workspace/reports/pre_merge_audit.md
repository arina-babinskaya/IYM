# Pre-merge audit: hybrid ML, GigaChat, and backend integration

Audit date: 2026-10-28  
Current branch: `ml-model`  
Target integration branch: `main` (`origin/HEAD -> origin/main`)  
Verdict: **READY WITH CONDITIONS**

The branch tip, local `main`, and `origin/main` all point to commit `5ae79fc`. All integration work
is currently uncommitted in the working tree. This audit did not commit, push, merge, rebase,
switch branches, modify remote branches, retrain the classifier, or modify a production database.

## A. Integration status

| Component | Implemented | Connected to backend | Tested | Working |
|---|---|---|---|---|
| TF-IDF classifier | Yes | Yes; default `trained` backend | Real artifact + API tests; local runtime | Yes, with pinned sklearn 1.6.1 condition |
| GigaChat fallback | Yes | Yes; real `/api/v1/admin/autobind` call path | Mock transport/API/E2E; no successful live call | Yes under mocks; live provider compatibility unverified |
| Product autobinding | Yes | Yes | Isolated SQLite endpoint test | Yes |
| Candidate retrieval | Yes | Yes | Repository, picker, hybrid E2E tests | Yes |
| Recommendations | Yes | Yes | Real sample catalog + API tests | Yes; no renovation-budget feature exists |
| Estimate generation | Yes | Yes; `/api/v1/estimate` | Tests + live local HTTP | Yes |
| GigaChat explanations | Yes | Yes; post-ranking only | Mocked E2E + failure tests | Yes under mocks; live provider compatibility unverified |
| Admin interface | Yes | Yes | API/template tests + local HTTP | API/template verified; browser clicks unverified |
| Calculator UI | Yes | Yes | Node syntax regression + local HTML/API | Parser failure fixed; browser clicks unverified |

Test labels in this table are deliberate: no successful real GigaChat classification/explanation
and no browser automation run were performed. A browser executable was not available.

## Runtime integration trace

### Classification and publication

1. `app/api/deps.py:get_classifier()` selects `TfidfClassifier` for the default
   `RC_ML_CLASSIFIER_BACKEND=trained`.
2. `TfidfClassifier` loads `ml_workspace/model/tfidf_logreg/model` once and converts the model's
   authoritative taxonomy-v2 predictions into backend `Suggestion` objects.
3. `POST /api/v1/admin/autobind` calls TF-IDF first for each unbound batch. The configured default
   threshold is exactly `0.7`.
4. `publishable()` accepts only confidence-at-threshold, taxonomy-consistent renovation results
   with one of the 38 `ProductCategory` values. It does not require a work type, so safe
   category/material-only bindings may be stored, but they cannot satisfy a specific estimate slot.
5. When GigaChat is enabled and credentials exist, low-confidence, unknown, `Material.other`, or
   taxonomy-conflicting renovation candidates are sent to `GigaChatClient.classify()`. Confident
   furniture and non-renovation products are excluded.
6. The client supplies the complete 38-category enum plus backend material/work enums, validates
   JSON with Pydantic, rejects invented labels, allows at most one controlled repair, and converts
   material/category or material/work conflicts to an explicit abstention.
7. Only evidence-backed `estimate_ready` GigaChat results are published. Rejection, uncertainty,
   invalid JSON/schema, taxonomy conflict, category-only output, outage, auth error, SSL error,
   timeout, or exhausted budget leaves the product unbound for the admin queue.
8. `CatalogRepo.save_ml_bindings()` uses conflict-do-nothing. Existing bindings, including manually
   confirmed ones, cannot be overwritten by either ML or GigaChat.
9. GigaChat exceptions are isolated per product, so TF-IDF publication and later products continue.

This is a real endpoint connection, not merely an unused client class: the isolated endpoint test
calls `/api/v1/admin/autobind`, observes the mocked GigaChat invocation, persists a validated
`source=gigachat` binding, and retrieves that product in a subsequent estimate.

### Recommendation, estimate, and explanation

The calculator request supplies rooms and work choices. The engine expands work choices into
materials, retrieves real `Product` + `ProductBinding` rows by both material and work type, then
filters inactive products, missing prices, insufficient binding confidence, out-of-stock products,
and required moisture flags. `ContextRanker` ranks remaining real catalog rows using product and
room signals. User picks may override the ranked first result, after which package quantities and
costs are calculated.

A hybrid-classified product can therefore appear only after a validated material/work binding is
persisted. Category-only/material-only bindings are excluded by the work-type filter. Room type,
humidity, active status, stock, price, packaging, and selected work are handled. There is no
renovation budget field in `EstimateRequest` and no total-budget optimization; only product option
price filters exist. This is a missing feature, not a hidden GigaChat behavior.

If request `explain` is true (the schema default and therefore also the current UI default), the
deterministic engine first finalizes products, prices, packages, and quantities. With
`RC_GIGACHAT_EXPLANATIONS=true`, the endpoint sends bounded facts about only those selected rows:
product name/price/unit/specs, room/work context, cost, deterministic reasons, and actual ranking
signals. Returned text can replace `item.reason` only. It cannot change products, prices,
quantities, or totals. Any GigaChat failure appends a warning and preserves the estimate and
deterministic `why` values.

The frontend renders `item.reason`, so explanations are connected to the calculator UI when the
backend option is enabled. There is no separate UI toggle; enablement is server configuration.
GigaChat does **not** select products. It classifies unresolved catalog products during autobinding
and optionally explains products already selected by deterministic retrieval/ranking.

## B. Test results

### Commands and exact outcomes

| Command | Outcome |
|---|---|
| `.venv-sandbox/bin/pytest -q` | **142 passed, 1 skipped**, 37 warnings, 73.04 s |
| `.venv-sandbox/bin/pytest -q tests/test_gigachat.py tests/test_hybrid_e2e.py` | **20 passed**, 1 warning |
| `.venv-sandbox/bin/pytest -q -rs tests/test_gigachat.py tests/test_hybrid_e2e.py tests/test_frontend.py tests/test_ingest_and_api.py` (before added cases) | **30 passed**, 1 warning |
| `.venv-sandbox/bin/pytest -q tests/test_db_migration.py tests/test_frontend.py` | **3 passed**, 1 warning |
| `.venv-sandbox/bin/python -m compileall -q app scripts ml_workspace/ml_api` | Passed |
| `git diff --check` | Passed; no whitespace errors |
| live Uvicorn + `curl` against `/tmp/iym_premerge_audit.sqlite` | Startup and all checked endpoints passed |
| Node parse of inline scripts returned from `/` | Passed; 75,883-byte HTML response |
| `docker build -t iym-premerge-audit:local .` | Not executed to completion: Docker Hub base-image metadata returned HTTP 403 |

The single skip is `tests/test_work_materials.py`: optional module
`ml_workspace.taxonomy.work_type_materials_v2` is absent. Node was available, so the frontend
syntax test itself ran and passed.

The full suite covers unit, classifier, catalog, ranking, estimate, API, frontend syntax, mocked
GigaChat, hybrid endpoint integration, and additive migration behavior. Added audit coverage proves:

- timeout, SSL-context, and authentication failures are normalized into recoverable GigaChat errors;
- invalid JSON/schema responses retain their reported token usage;
- a repair attempt and retry attempt are independently accounted;
- the request/token budget is rechecked before each retry;
- category-only/rejected/uncertain/conflicting output is not published;
- confirmed bindings survive autobinding;
- an old database gains `product_category` without changing a confirmed row.

### Live local HTTP observations

Using a fresh isolated SQLite database and `mock_catalog/sample_catalog.json` (27 products), with
GigaChat explicitly disabled:

- `/health`: HTTP 200, database OK; Ollama unavailable (non-fatal for the deterministic engine).
- `/api/v1/taxonomy`: 5 stages, 10 room types, 4 renovation types, 20 works, 56 materials, and
  exactly 38 product categories.
- `/api/v1/admin/products?status=ml&limit=5`: 3 rows, all with bindings.
- `/api/v1/estimate`: HTTP 200; bathroom wall tiling chose catalog product 96612, 19 packages,
  total 24,510 RUB, no warnings.
- `/`: HTTP 200 and parseable inline JavaScript.

No real browser was available, so wizard interaction, visual layout, admin button clicks, and the
visible explanation presentation remain browser-unverified. Backend tests alone are not being used
to claim a fully working website.

### Model compatibility

The tracked artifact records Python 3.13.16, NumPy 2.1.3, pandas 2.2.3, scikit-learn **1.6.1**, and
joblib 1.6.0. `requirements.txt` pins those numerical/ML versions, and the Dockerfile uses Python
3.13. The required artifact is tracked (approximately 49 MB combined joblib files) and its files
load successfully.

The audit sandbox instead used Python 3.14.4 and scikit-learn 1.9.1. Loading succeeds but produces
`InconsistentVersionWarning` for `LogisticRegression`, `LabelBinarizer`, `OneVsRestClassifier`,
`TfidfTransformer`, and `TfidfVectorizer`. Results under 1.9.1 are not a supported deployment
claim. A clean environment must use the pinned requirements. Docker could not verify that clean
path because the environment blocked `registry-1.docker.io` with HTTP 403.

## C. Integration blockers and risks

### BLOCKER

No remaining code blocker was reproduced after the SSL/retry fix.

### IMPORTANT — conditions before push/merge or deployment

1. **Working tree packaging:** all branch work is uncommitted. Review exactly which untracked files
   belong in the change. Do not accidentally include the ignored `.env`, `.cache/gigachat.sqlite`,
   virtual environments, local databases, datasets, or generated experiment output.
2. **Accidental tracked file:** `.DS_Store` is tracked and modified. It has no product value and
   should be removed from Git in a separate user-approved cleanup; this audit did not delete or
   revert it.
3. **Generated/untracked artifacts:** `ml_workspace/outputs/` contains a roughly 79 MB prediction
   CSV plus generated pilot files. Most named result CSVs are ignored, but
   `manual_annotation_template.csv` and the directory itself still appear untracked. Decide what is
   evidence versus generated output before staging. The experiment notebook and three reports are
   also untracked and need intentional review.
4. **Certificates:** `certs/` is untracked. The files inspected are public CA material, not private
   keys; the Russian Trusted Root CA is valid until 2032. Still review the 236 KB bundle before
   adding it. Never add client keys or credentials.
5. **Local credential hazard:** the ignored local `.env` currently has GigaChat enabled and a
   credential present. As a result, ordinary ingest/autobind attempts network calls. During this
   audit, isolated sample ingestion made OAuth attempts; each returned HTTP 403 and no chat request
   succeeded. No secret was printed and no production DB was used. Disable GigaChat during normal
   ingest and enable it only for an explicit bounded pilot.
6. **Clean dependency verification:** recreate Python 3.13 with `requirements.txt` so inference uses
   scikit-learn 1.6.1. Do not deploy from the audit's 1.9.1 environment.
7. **Docker/PostgreSQL/browser:** Docker build was blocked by registry policy, PostgreSQL was not
   started, and click-level browser testing was unavailable. Run the local checklist below on the
   Mac before a demo/deployment.
8. **Migration mechanism:** `product_category` is added by an idempotent startup migration in
   `init_db`; there is no Alembic/versioned migration framework. The SQLite upgrade is tested and
   preserves confirmed rows, but the team should run a backed-up PostgreSQL staging upgrade before
   production deployment.
9. **Merge overlap:** `main` is the actual target and has no committed divergence from this branch,
   but the work modifies shared integration files. Current `origin/front` overlaps in README,
   picker/routes/repository/config/schemas/static HTML/tests; current `origin/backend` overlaps in
   nearly every shared backend file and deletes `app/ml/tfidf.py` and much of `ml_workspace`.
   Integrating those feature branches later will require deliberate conflict resolution and must
   retain the model artifact, hybrid call path, migration, and frontend parser fix.

### OPTIONAL — suitable after the hackathon

- Add first-class renovation budget input and constrained selection. It does not currently exist.
- Add browser E2E automation and a visible explanation enable/disable control.
- Replace startup DDL with versioned migrations.
- Add a checked-in lint/type configuration. No Ruff, mypy, or pyright configuration/tool was
  present; compile and import checks were used instead.
- Resolve the deprecated Starlette/FastAPI TestClient warning when the dependency stack supports it.

## Security and artifact audit

- `.env` is ignored and not tracked. No credential value was read or printed.
- No tracked hard-coded credential was found by the targeted scan.
- SSL verification defaults to true. The implementation was fixed to degrade safely on invalid
  SSL context construction; verification was not disabled.
- No Mac-specific absolute path exists in runtime code. An older report contains the expected
  local repository path for instructions only.
- Ignored local material includes `.cache/`, `.pytest_cache/`, `.venv*`, `__pycache__`, local SQLite
  databases, `data/`, and multi-gigabyte `ml_workspace/data/` datasets.
- Large tracked files include the required 45 MB estimator artifact, a 12 MB generated comparison
  CSV, and older model artifacts. The 45 MB artifact is operationally required; the comparison CSV
  and stale artifacts deserve a later repository-size review but were not introduced by this
  working-tree change.

## API and schema changes

- `Suggestion`, `BindingIn`, `BindingOut` serialization, and `/taxonomy` now carry
  `product_category` from the authoritative 38-category enum.
- `product_bindings.product_category VARCHAR(64) NULL` and an index are additive. Existing rows
  retain `NULL`; material/work/confirmed/source data is unchanged.
- New configuration variables are the `RC_GIGACHAT_*` family, classifier backend/artifact settings,
  and `RC_AUTOBIND_MIN_CONFIDENCE` documented in `.env.example`.
- No new runtime Python dependency was added beyond the pinned requirements already used by the
  implementation (`httpx`, Pydantic, SQLAlchemy, scikit-learn/joblib stack).

## D. Merge readiness

**READY WITH CONDITIONS**

The hackathon implementation is functionally integrated under mocked GigaChat and an isolated real
catalog/database. The actual autobind endpoint calls the fallback, accepted hybrid bindings reach
retrieval and estimates, explanation calls occur only after selection, failures degrade safely,
the migration preserves confirmed bindings, the blank-page syntax defect is fixed, and all 142
executed tests pass.

Before push/merge, the owner should: review/stage only intended untracked files; exclude generated
outputs and secrets; address the tracked `.DS_Store`; verify a Python 3.13/scikit-learn 1.6.1 clean
install; run Docker/PostgreSQL and browser smoke tests; and perform the explicit 5–10-product live
pilot below. A successful live GigaChat or real browser run is not claimed.

## E. Local verification instructions (macOS, Fish shell)

All commands use the actual repository path.

### 1. Environment setup

```fish
cd /Users/arinababinskaya/Documents/GitHub/IYM
python3.13 -m venv .venv-audit
source .venv-audit/bin/activate.fish
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -c 'import sklearn; assert sklearn.__version__ == "1.6.1", sklearn.__version__; print(sklearn.__version__)'
cp .env.example .env.audit
```

Keep the existing `.env` untouched. For safe offline commands, override GigaChat explicitly:

```fish
set -gx RC_GIGACHAT_ENABLED false
set -gx RC_DATABASE_URL sqlite:///./repaircalc_audit.sqlite
set -gx RC_ML_CLASSIFIER_BACKEND trained
set -gx RC_ML_CLASSIFIER_ARTIFACT_PATH ml_workspace/model/tfidf_logreg/model
set -gx RC_AUTOBIND_MIN_CONFIDENCE 0.7
```

### 2. Apply the additive migration safely and load the sample catalog

For SQLite, back up an existing audit database before migration:

```fish
test -f repaircalc_audit.sqlite; and cp repaircalc_audit.sqlite repaircalc_audit.sqlite.pre_product_category.bak
python -c 'from app.db import init_db; init_db(); print("migration complete")'
python -m scripts.ingest --file mock_catalog/sample_catalog.json
```

For the Docker/PostgreSQL path, preserve the volume and apply startup migration without deleting
data:

```fish
docker compose up -d postgres
docker compose run --rm --entrypoint python api -c 'from app.db import init_db; init_db(); print("migration complete")'
docker compose run --rm ingest --file mock_catalog/sample_catalog.json
```

Do not run `docker compose down -v`; that would delete the PostgreSQL volume.

### 3. Start the backend

```fish
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second Fish terminal:

```fish
curl -fsS http://127.0.0.1:8000/health | python -m json.tool
curl -fsS http://127.0.0.1:8000/api/v1/taxonomy | python -m json.tool
```

### 4. Run tests and static/import checks

```fish
python -m pytest -q
python -m pytest -q tests/test_gigachat.py tests/test_hybrid_e2e.py tests/test_db_migration.py tests/test_frontend.py
python -m compileall -q app scripts ml_workspace/ml_api
git diff --check
```

Expected audit result: 142 passed and 1 optional-reference skip.

### 5. Test the hybrid classifier without live GigaChat

```fish
set -gx RC_GIGACHAT_ENABLED false
python -m scripts.gigachat_fallback --limit 10
curl -fsS -X POST 'http://127.0.0.1:8000/api/v1/admin/autobind?batch=100' | python -m json.tool
curl -fsS 'http://127.0.0.1:8000/api/v1/admin/products?status=ml&limit=10' | python -m json.tool
```

The first command is a no-network, no-write preview. The endpoint writes only missing safe ML
bindings at the 0.7 threshold.

### 6. Run a safe real GigaChat pilot (5–10 products, no DB writes)

Do not paste the credential into command history. Use a new cache namespace and retain SSL
verification:

```fish
read -s -P 'GigaChat Authorization Key: ' RC_GIGACHAT_CREDENTIALS
set -gx RC_GIGACHAT_CREDENTIALS $RC_GIGACHAT_CREDENTIALS
set -gx RC_GIGACHAT_ENABLED true
set -gx RC_GIGACHAT_VERIFY_SSL true
set -gx RC_GIGACHAT_CA_BUNDLE certs/gigachat_ca_bundle.pem
set -gx RC_GIGACHAT_MAX_REQUESTS 10
set -gx RC_GIGACHAT_TOKEN_BUDGET 15000
set -gx RC_GIGACHAT_TOKEN_RESERVATION 2500
set -gx RC_GIGACHAT_AUTOBIND_MAX_PRODUCTS 10
set -gx RC_GIGACHAT_CACHE_NAMESPACE pilot-2026-10-28-v1
python -m scripts.gigachat_fallback --limit 10
python -m scripts.gigachat_fallback --limit 10 --use-api --cache-namespace pilot-2026-10-28-v1
set -e RC_GIGACHAT_CREDENTIALS
set -gx RC_GIGACHAT_ENABLED false
```

Do **not** add `--apply` during the pilot. Inspect `.cache/gigachat.sqlite` and the printed counts;
verify schema validity, conflicts, retries, unknown token usage, total usage, and latency before any
separately authorized write run.

### 7. Create a complete renovation estimate

With the backend running:

```fish
curl -fsS -X POST http://127.0.0.1:8000/api/v1/estimate \
  -H 'content-type: application/json' \
  --data '{"renovation_type":"capital","explain":false,"rooms":[{"name":"Ванная","room_type":"bathroom","length_m":2,"width_m":3,"height_m":2.5,"windows":0,"doors":1,"works":[{"work_type":"tiling","surface":"wall","materials":["tile"]},{"work_type":"wall_painting","surface":"ceiling","materials":["primer","paint"]},{"work_type":"lighting_install","materials":["lighting"]}]}]}' \
  | python -m json.tool
```

Check that every priced row has a real product ID/name, price, package count, cost, and deterministic
`why`; missing catalog coverage should appear as a warning rather than an application error.

### 8. Check GigaChat explanations without allowing product changes

After the no-write pilot succeeds, start a new backend process with the credential set locally:

```fish
read -s -P 'GigaChat Authorization Key: ' RC_GIGACHAT_CREDENTIALS
set -gx RC_GIGACHAT_CREDENTIALS $RC_GIGACHAT_CREDENTIALS
set -gx RC_GIGACHAT_ENABLED true
set -gx RC_GIGACHAT_EXPLANATIONS true
set -gx RC_GIGACHAT_VERIFY_SSL true
set -gx RC_GIGACHAT_CA_BUNDLE certs/gigachat_ca_bundle.pem
set -gx RC_GIGACHAT_MAX_REQUESTS 10
set -gx RC_GIGACHAT_TOKEN_BUDGET 15000
set -gx RC_GIGACHAT_CACHE_NAMESPACE explanation-pilot-2026-10-28-v1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Repeat the estimate request with `"explain":true`. Compare product IDs, prices, packages,
quantities, and total against the `explain:false` response: they must be identical. Only `reason`
and possible warnings may differ. Stop the server and clear the shell credential:

```fish
set -e RC_GIGACHAT_CREDENTIALS
```

### 9. Verify the browser application

```fish
open http://127.0.0.1:8000/
```

In Safari/Chrome developer tools, confirm there is no `Unexpected token '<'` error. Complete the
wizard, generate an estimate, inspect real products/prices/package counts, open alternatives, and
visit the admin tab. With explanations enabled, confirm explanation text appears without changing
the selected products or totals. Trigger a safe explanation failure by stopping network access and
confirm the estimate still renders with a warning and deterministic reasons.

Finally inspect the working tree before any future staging action:

```fish
git status --short --branch
git diff --check
git diff --stat main --
```
