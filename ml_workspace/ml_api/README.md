# Единый ML API RepairCalc

Публичные функции экспортируются из `ml_api`:

```python
load_data(
    clean_path: Path,
    weak_labels_path: Path,
    reviewed_paths: Sequence[Path],
    split_manifest_path: Path,
    taxonomy_path: Path,
    taxonomy_version: str,
    label_policy: str = "reviewed_only",
    random_seed: int = 20261023,
) -> DatasetBundle

prepare_features(
    data: DatasetBundle,
    config: TrainingConfig,
    cache_dir: Path | None = None,
    encoder: SentenceEncoder | None = None,
) -> FeatureBundle

train(features: FeatureBundle, config: TrainingConfig) -> ModelBundle
validate(model: ModelBundle, features: FeatureBundle) -> ValidationResult
evaluate(model: ModelBundle, features: FeatureBundle, split: str = "test") -> EvaluationResult
save_model(model: ModelBundle, artifact_dir: Path,
           validation: ValidationResult | None = None,
           evaluation: EvaluationResult | None = None) -> None
load_model(artifact_dir: Path, expected_taxonomy_version: str,
           trusted: bool = False, encoder: SentenceEncoder | None = None) -> ModelBundle
predict(model: ModelBundle,
        products: ProductInput | Sequence[ProductInput]) -> Prediction | list[Prediction]
compute_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                y_score: np.ndarray | None = None,
                class_names: list[str] | None = None,
                top_k: int = 3) -> dict[str, Any]
```

`DatasetBundle.frame` содержит одну строку на товар, `labels: list[str]`, `split`, provenance и `is_verified`. `FeatureBundle` содержит `X` по split и бинарные `Y` формы `(n, n_classes)`. Порядок столбцов всегда равен `class_names` из указанной версии таксономии.

`validate()` единственный выбирает thresholds и использует только validation. `evaluate()` thresholds не меняет. `predict()` принимает один товар или batch.

Поддержанные эксперименты:

- `tfidf_logreg`: sparse TF-IDF + OvR Logistic Regression;
- `embeddings_logreg`: fixed sentence embeddings + OvR Logistic Regression;
- `catboost_structured`: отдельный CatBoost binary classifier на каждый work type;
- будущий transformer backend должен возвращать тот же `ModelBundle` и scores формы `(n, n_classes)`, поэтому RuBERT/RoBERTa можно добавить без изменения notebook workflow.

Загрузка joblib разрешена только при `trusted=True`: serialized artifacts нельзя принимать от недоверенного источника.
