import json
from pathlib import Path

import pandas as pd

from taxonomy_config import PRODUCT_TAXA, ROOM_TAXA, USAGE_TAXA


ROOT = Path(__file__).resolve().parents[2]


def test_data_integrity_and_label_parsing():
    clean = pd.read_csv(ROOT / "ml_workspace/data/products_clean.csv", usecols=["product_id", "cod_good"], dtype={"cod_good": "string"})
    labels = pd.read_csv(ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv")
    assert len(clean) == len(labels) == 88790
    assert clean.product_id.is_unique and labels.product_id.is_unique
    for column in ["proposed_product_categories", "proposed_work_types", "proposed_room_types", "proposed_usage_contexts"]:
        assert labels[column].map(lambda x: isinstance(json.loads(x), list)).all()


def test_taxonomy_ids_valid():
    labels = pd.read_csv(ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv")
    vocab = {
        "proposed_product_categories": {x.taxon_id for x in PRODUCT_TAXA},
        "proposed_room_types": {x.taxon_id for x in ROOM_TAXA},
        "proposed_usage_contexts": {x.taxon_id for x in USAGE_TAXA},
    }
    for column, allowed in vocab.items():
        assert labels[column].map(lambda x: set(json.loads(x)) <= allowed).all()


def test_no_split_group_leakage_if_artifact_exists():
    path = ROOT / "ml_workspace/artifacts/experiment_1/splits.csv"
    if path.exists():
        splits = pd.read_csv(path)
        assert splits.groupby("leakage_group").split.nunique().max() == 1
