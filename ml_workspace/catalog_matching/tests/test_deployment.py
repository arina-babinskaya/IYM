import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.ml.catalog_matching import CatalogMatchInput, CatalogMatchingClassifier
from ml_workspace.catalog_matching.inference.predictor import CatalogArtifactError, CatalogPredictor
from ml_workspace.catalog_matching.taxonomy.catalog_taxonomy import CATEGORY_BY_ID, TAXONOMY_VERSION

ROOT = Path(__file__).parents[3]
ARTIFACT = ROOT / "ml_workspace/catalog_matching/data/artifact"


@pytest.fixture(scope="module")
def predictor():
    if not ARTIFACT.is_dir():
        pytest.skip("trained catalog classifier artifact is unavailable")
    return CatalogPredictor(ARTIFACT)


def lightweight_artifact(tmp_path: Path) -> Path:
    target = tmp_path / "artifact"
    target.mkdir()
    for name in ("metadata.json", "taxonomy.json", "checksums.json"):
        shutil.copy2(ARTIFACT / name, target / name)
    (target / "model.joblib").symlink_to(ARTIFACT / "model.joblib")
    return target


def test_artifact_loads_and_validates_taxonomy(predictor):
    assert predictor.metadata["taxonomy_version"] == TAXONOMY_VERSION
    assert len(predictor.model.classes_) == 90
    assert set(predictor.model.classes_) == set(CATEGORY_BY_ID) - {"review.unresolved"}


def test_missing_and_corrupt_artifacts_are_actionable(tmp_path):
    with pytest.raises(CatalogArtifactError, match="missing required files"):
        CatalogPredictor(tmp_path)
    artifact = lightweight_artifact(tmp_path)
    (artifact / "metadata.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CatalogArtifactError, match="checksum mismatch: metadata.json"):
        CatalogPredictor(artifact)


def test_single_batch_top_three_name_only_and_deterministic(predictor):
    one = predictor.predict_category("Ножницы для живой изгороди", description="ignored description", top_k=3)
    repeated = predictor.predict_category("Ножницы для живой изгороди", top_k=3)
    assert one == repeated
    assert one.category_id == "garden.tools"
    assert len(one.alternatives) == 2
    scores = [one.confidence, *(item.confidence for item in one.alternatives)]
    assert scores == sorted(scores, reverse=True)
    assert one.category_id in CATEGORY_BY_ID
    batch = predictor.predict_batch(["Ножницы для живой изгороди", "неизвестный товар xyz"])
    assert len(batch) == 2 and all(item.category_id in CATEGORY_BY_ID for item in batch)
    with pytest.raises(ValueError, match="non-empty"):
        predictor.predict_category(" ")


def test_adapter_preserves_catalog_contract_and_loads_once(monkeypatch):
    calls = 0
    original = CatalogPredictor.__init__

    def counted(self, path, *args, **kwargs):
        nonlocal calls
        calls += 1
        original(self, path, *args, **kwargs)

    monkeypatch.setattr(CatalogPredictor, "__init__", counted)
    adapter = CatalogMatchingClassifier(ARTIFACT)
    results = adapter.predict_batch([
        CatalogMatchInput(1, "Ножницы для живой изгороди"),
        {"id": 2, "name": "Кабель ВВГнг 3x2.5"},
    ])
    adapter.predict_one({"id": 3, "name": "Смеситель для кухни"})
    assert calls == 1
    assert [item.product_id for item in results] == [1, 2]
    assert all(item.taxonomy_version == TAXONOMY_VERSION for item in results)
    assert not hasattr(results[0], "material") and not hasattr(results[0], "work_types")


def test_model_loads_in_fresh_process():
    code = (
        "from ml_workspace.catalog_matching.inference.predictor import CatalogPredictor; "
        f"p=CatalogPredictor({str(ARTIFACT)!r}); "
        "print(p.predict_category('Ножницы для живой изгороди').category_id)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "garden.tools"


def test_ranking_modules_do_not_reference_catalog_matcher():
    protected = [
        ROOT / "app/ml/ranker.py", ROOT / "app/ml/baseline.py",
        ROOT / "app/catalog/repository.py", ROOT / "app/engine/baseline.py",
    ]
    for path in protected:
        source = path.read_text(encoding="utf-8")
        assert "CatalogPredictor" not in source
        assert "CatalogMatchingClassifier" not in source
        assert "catalog_matching_artifact_path" not in source


def test_ranking_configuration_is_independent(monkeypatch):
    from app.api.deps import get_ranker
    from app.config import get_settings

    monkeypatch.setenv("RC_CATALOG_MATCHING_ARTIFACT_PATH", "/definitely/missing")
    get_settings.cache_clear(); get_ranker.cache_clear()
    try:
        ranker = get_ranker()
        assert ranker.__class__.__name__ == "ContextRanker"
    finally:
        get_settings.cache_clear(); get_ranker.cache_clear()

