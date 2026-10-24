# ML workspace cleanup proposal

No destructive cleanup was performed. This proposal follows the repository import/reference audit
and requires approval before deletion or relocation.

## Safe generated-cache deletions (completed 2026-10-24)

These contain no source or reproducibility data and are regenerated automatically:

- `.pytest_cache/`
- `app/__pycache__/`, `app/api/__pycache__/`, `app/catalog/__pycache__/`,
  `app/engine/__pycache__/`, `app/llm/__pycache__/`, `app/ml/__pycache__/`
- `ml_workspace/__pycache__/`, `ml_workspace/experiments/__pycache__/`,
  `ml_workspace/ml_api/__pycache__/`, `ml_workspace/recommendation/__pycache__/`,
  `ml_workspace/scripts/__pycache__/`, `ml_workspace/taxonomy/__pycache__/`,
  `ml_workspace/tests/__pycache__/`
- `scripts/__pycache__/`, `tests/__pycache__/`

These listed caches were confirmed untracked/ignored and removed during final handoff verification.
The archived legacy-workflow cache was not listed and was left untouched.

The modified root `.DS_Store` is unrelated pre-existing user work and is not proposed for deletion.

## Retain

- `ml_workspace/data/splits_v2/` and `splits_v3/`, all three `experiments_v3/` directories, raw
  catalog inputs, manifests, and provenance.
- `ml_workspace/notebooks/train_and_evaluate_colab.ipynb`, v3 dataset builders/weak-label rules,
  unified ML API, tests, backend adapter/fallback, ranking code and handoff documents.
- `taxonomy_v2.py` and all v2 CSV definitions as the only active runtime taxonomy.
- `taxonomy_v1.py`, v1 CSVs, v1 builders/tests/reports, and old artifacts as historical inputs.
  They are referenced by reproducibility scripts/tests and must not be deleted under the task rules.
- `ml_workspace/artifacts/models/tfidf_logreg_v2/` as a rollback/historical artifact. It differs by
  checksum from the selected v3 artifact and must not be mistaken for the deployment candidate.
- Existing `ml_workspace/archive/` contents; they already isolate retired workflows and are useful
  for provenance.

## Uncertain; report only

- `ml_workspace/artifacts/experiment_1/`, `smoke_taxonomy_v1/`, and `smoke_taxonomy_v2/` are older
  tracked artifacts referenced by reports/tests or historical delivery material. Archiving them
  might improve navigation but would require coordinated path updates, so no move is proposed.
- `ml_workspace/scripts/for_myy_tests.ipynb` has an exploratory name but content provenance was not
  sufficient to classify it as obsolete. Retain pending owner confirmation.
- Draft taxonomy CSVs remain historical design/provenance material and are not active runtime
  dependencies. Retain rather than infer that “draft” means disposable.

Active Python runtime imports now resolve only `taxonomy_v2`; remaining taxonomy-v1 imports occur
in explicitly historical generation scripts and v1 tests.
