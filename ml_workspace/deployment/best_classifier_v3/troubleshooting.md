# Troubleshooting

- **`Incomplete model artifact`**: confirm all seven files are directly under the configured model
  directory and rerun the SHA-256 command from the README.
- **Checksum failure**: do not load the artifact. Remove only the bad copy and obtain it again from
  the approved internal source.
- **`PermissionError: trusted=True required`**: use the documented `load_model(..., trusted=True)`
  only after verifying provenance and checksums. Joblib files can execute code while loading.
- **scikit-learn `InconsistentVersionWarning`**: recreate the environment with Python 3.13 and the
  pinned handoff requirements. Do not treat a warning from a newer version as supported deployment.
- **Taxonomy mismatch or missing task/threshold error**: the configured directory is not this
  `taxonomy_v2` format-2 artifact; do not bypass validation.
- **Backend fails during startup**: check `RC_ML_CLASSIFIER_ARTIFACT_PATH`, then run the standalone
  inference example. Roll back with `RC_ML_CLASSIFIER_BACKEND=baseline` while correcting deployment.
- **Empty work-type list**: this can be a valid thresholded result. Inspect `scores`, saved
  thresholds, domain status, and unsupported-label flags; do not force a top-one label.
