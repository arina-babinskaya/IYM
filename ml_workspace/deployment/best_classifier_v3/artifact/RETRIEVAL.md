# Artifact retrieval

The binary artifact is not stored in Git and must not be downloaded from an untrusted location.
Obtain the selected `tfidf_logreg` `splits_v3` artifact from the project owner or the team's approved
internal artifact store. No public URL or credential is embedded in this package.

Install exactly these files—without an additional nested `model/` directory—at
`ml_workspace/data/experiments_v3/tfidf_logreg/model/`:

- `dependency_versions.json`
- `estimators.joblib`
- `evaluation_metrics.json`
- `metadata.json`
- `preprocessor.joblib`
- `thresholds.json`
- `validation_metrics.json`

The expected total file size is 51,729,661 bytes. Verify every file with `manifest.sha256` before
using `trusted=True`. A checksum failure means the artifact must not be loaded; obtain a clean copy.
