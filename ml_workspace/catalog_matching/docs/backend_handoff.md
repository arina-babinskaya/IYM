# Backend handoff

This classifier assigns one full-catalog product leaf during new-product onboarding. It is not the renovation multi-label/work-type classifier and must be loaded and invoked independently. No production integration is included here.

Install the locked/project ML dependencies, then instantiate `CatalogPredictor(artifact_directory)`. Call `predict_category(product_name, description=None, top_k=3)`. The primary result always contains one `category_id`, Russian `category_name`, an uncalibrated model probability, model name, and `needs_review`; alternatives are administrator suggestions, not extra assignments.

An artifact directory contains `model.joblib`, `metadata.json`, `taxonomy.json`, and `checksums.json`. Loading verifies checksums. Metadata records feature mode, class order, configuration, dependencies, dataset fingerprint, metrics, and an optional validation-selected review threshold. Do not describe probabilities as calibrated unless calibration has been evaluated. Unknown/out-of-domain products still get top-1, normally with low score and `needs_review` when a threshold is configured.

For batches, load once and call the underlying pipeline's `predict_proba` on a list, applying the same feature-mode composition as the predictor. Never pass source category, IDs, weak-label metadata, or split fields as features.

The expected integration point is a separate onboarding/admin endpoint. Keep its artifact path, environment variable, API schema, logs, and lifecycle distinct from `KeywordClassifier`, renovation model selection, and ranking. A smoke test needs no training data: load the artifact, predict several literal product names, assert exactly one known ID, finite probability, optional alternatives, and deterministic repeated output.
