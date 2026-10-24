# Best classifier v3: backend handoff

The provisional deployment candidate is `tfidf_logreg`, trained on `splits_v3` / `weak_rules_v3`
with `taxonomy_v2`. It has the strongest saved work-type results, the best measured multi-label
subset result, CPU-only inference, and no network download at runtime. Scores are probabilities from
one-vs-rest logistic regressions; a work type is returned when its score reaches the class-specific
value in `thresholds.json`.

The 51,729,661-byte artifact is intentionally not duplicated or committed. Obtain its seven files
from the project owner or the team's approved internal artifact store as described in
`artifact/RETRIEVAL.md`. Place them at the exact path
`ml_workspace/data/experiments_v3/tfidf_logreg/model/`.

From the repository root, create the supported environment and verify the installation:

```bash
python3.13 -m venv .venv-model
.venv-model/bin/python -m pip install --upgrade pip
.venv-model/bin/python -m pip install -r requirements.txt
.venv-model/bin/python -m pip install -r ml_workspace/deployment/best_classifier_v3/requirements.txt
(cd ml_workspace/data/experiments_v3/tfidf_logreg/model && sha256sum -c ../../../../deployment/best_classifier_v3/artifact/manifest.sha256)
PYTHONPATH=. .venv-model/bin/python ml_workspace/deployment/best_classifier_v3/inference_example.py
.venv-model/bin/python -m pytest -q tests/test_tfidf_classifier.py
```

Only load artifacts from a trusted source: joblib serialization can execute code. No Google Drive,
training data, GPU, credentials, or external model download is needed after these files are present.

Enable the cached FastAPI adapter with:

```bash
export RC_ML_CLASSIFIER_BACKEND=trained
export RC_ML_CLASSIFIER_ARTIFACT_PATH=ml_workspace/data/experiments_v3/tfidf_logreg/model
.venv-model/bin/python run_local.py
```

Rollback is `RC_ML_CLASSIFIER_BACKEND=baseline` (or removing the variable). The legacy value
`tfidf` remains an alias for `trained`. Missing/incompatible artifacts fail startup with a
`ClassifierArtifactError`; they do not silently change predictions. See `api_contract.md`,
`taxonomy_mapping.md`, `verification_report.md`, and `troubleshooting.md` for integration details
and limitations.
