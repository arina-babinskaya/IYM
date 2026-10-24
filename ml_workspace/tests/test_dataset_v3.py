from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_workspace.ml_api import load_data, prepare_features
from ml_workspace.ml_api.types import TrainingConfig
from ml_workspace.scripts.build_taxonomy_v3_dataset import SEED, group_multilabel_split
from ml_workspace.scripts.weak_labeling_v3 import label_product
from ml_workspace.taxonomy.taxonomy_v2 import WORK_IDS

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ROOT / "ml_workspace/data/splits_v3"
MASTER = ROOT / "ml_workspace/data/products_taxonomy_v3.csv"


def row(name: str, category: str, characteristics: str = "[]") -> dict[str, str]:
    return {"name": name, "source_category": category, "description_clean": "",
            "marketing_description_clean": "", "important_attributes_json": "{}",
            "characteristics_json": characteristics}


def test_explicit_secondary_labels_are_additive_and_preserved() -> None:
    result = label_product(row(
        "шпатлевка гипсовая для внутренних работ",
        "Шпатлевки сухие гипсовые",
        '[{"name":"Описание","value":"Для заделки швов гипсокартона под окраску"}]'))
    assert {"wall_putty", "drywall_install", "wall_painting"}.issubset(result["work_types"])


@pytest.mark.parametrize(("name", "category", "present", "absent"), [
    ("Кувалда 2 кг", "Кувалды", "demolition", None),
    ("Ровнитель пола", "Смеси для выравнивания полов цементные", "floor_screed", None),
    ("Кран шаровый", "Запорная арматура для трубопроводов", "plumbing_rough", "electrical_wiring"),
    ("Теплый пол", "Теплый пол под ламинат, паркет, линолеум и ковролин", "heating_climate_install", "floor_covering_install"),
])
def test_rare_coverage_and_disambiguation(name: str, category: str, present: str, absent: str | None) -> None:
    labels = label_product(row(name, category))["work_types"]
    assert present in labels
    if absent:
        assert absent not in labels


def test_group_multilabel_split_is_deterministic_and_group_isolated() -> None:
    frame = pd.DataFrame([
        {"duplicate_group": f"g{i // 2}", "work_types": json.dumps(
            ["waterproofing", "tiling"] if i % 7 == 0 else ["demolition"] if i % 11 == 0 else []),
         "work_types_valid": True}
        for i in range(120)
    ])
    first = group_multilabel_split(frame, SEED)
    second = group_multilabel_split(frame, SEED)
    assert first.equals(second)
    assert pd.DataFrame({"group": frame.duplicate_group, "split": first}).groupby("group").split.nunique().max() == 1


def test_generated_v3_integrity_and_round_trip(tmp_path: Path) -> None:
    required = {"train.csv", "validation.csv", "test.csv", "split_manifest.csv",
                "class_support.csv", "dataset_manifest.json", "label_change_audit.csv"}
    assert required.issubset({path.name for path in SPLITS.iterdir()})
    parts = [pd.read_csv(SPLITS / f"{split}.csv", keep_default_na=False, low_memory=False)
             for split in ("train", "validation", "test")]
    data = pd.concat(parts, ignore_index=True)
    assert not data.product_id.duplicated().any()
    assert data.groupby("duplicate_group").split.nunique().max() == 1
    assert set(label for value in data.work_types.map(json.loads) for label in value) <= set(WORK_IDS)
    assert all(isinstance(value, list) for value in data.work_types.map(json.loads))
    round_trip = tmp_path / "round_trip.csv"
    data.head(100).to_csv(round_trip, index=False)
    restored = pd.read_csv(round_trip, keep_default_na=False)
    assert restored.work_types.map(json.loads).tolist() == data.head(100).work_types.map(json.loads).tolist()


class MockEncoder:
    def encode(self, texts: list[str], **_: object) -> np.ndarray:
        return np.array([[len(text), text.count("грунт")] for text in texts], dtype=float)


@pytest.mark.parametrize("experiment", ["tfidf_logreg", "catboost_structured", "embeddings_logreg"])
def test_existing_feature_preparation_loads_v3(experiment: str) -> None:
    data = load_data(MASTER)
    features = prepare_features(data, TrainingConfig(experiment=experiment, max_features=100),
                                encoder=MockEncoder() if experiment == "embeddings_logreg" else None)
    assert set(features.x_by_split) == {"train", "validation", "test"}
    for split in ("train", "validation", "test"):
        source = data.frame[data.frame.split.eq(split)]
        assert np.array_equal(features.supervision_mask_by_task["work_types"][split],
                              source.work_types_valid.astype(bool).to_numpy())
    assert any(len(labels) > 1 for labels in data.frame.labels)
