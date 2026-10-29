# Full-catalog category matching

Independent single-label, multi-class categorization for all Maxidom products. It does not import or modify renovation `taxonomy_v2`, work types, artifacts, APIs, ranking, backend, or database behavior.

## Workflow

From repository root:

```bash
python3 -m ml_workspace.catalog_matching.build_dataset \
  --catalog requirments/products_final.json \
  --output ml_workspace/catalog_matching/data/splits_v2 \
  --mapping ml_workspace/catalog_matching/taxonomy/source_category_mapping_v2.csv
python3 -m ml_workspace.catalog_matching.analyze_coverage_v2
pytest -q ml_workspace/catalog_matching/tests
```

The builder parses original inspection fields, applies deterministic source-ID/name and narrow product-name weak labels, writes a complete mapping/review audit, and creates seeded class-aware group splits from confident rows. CSVs are intentionally Git-ignored because they are large; copy `splits_v2` to Google Drive and retain `metadata.json` checksums and `taxonomy_snapshot.json`. Source category is label provenance only. Default model text is product name; optional `name_description` uses descriptions/characteristics available before prediction.

Open `notebooks/train_catalog_classifier_colab.ipynb` in Colab, set repository and Drive paths, and run in order. The notebook installs dependencies, uses a token from Colab Secrets for a private clone, mounts Drive, validates checksums/schema/isolation, visualizes classes, selects hyperparameters on validation only, evaluates the untouched weak-label test set, saves a versioned complete artifact, and reloads it for inference. Never commit tokens, raw JSON, split CSVs, or artifacts.

Metrics measure agreement with weak labels, not independently verified accuracy. Review taxonomy decisions in `reports/catalog_analysis.md`, definitions in `reports/taxonomy_v1.md`, and production guidance in `docs/backend_handoff.md`.
