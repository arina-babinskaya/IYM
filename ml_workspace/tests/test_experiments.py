import sys
from pathlib import Path

import numpy as np
import pandas as pd

import experiment_1_tfidf as exp1
import experiment_2_embeddings as exp2


def synthetic_data():
    rows = []
    labels = ["tiling", "wall_painting"]
    for i in range(60):
        label = labels[i % 2]
        rows.append({"product_id": i + 1, "text": f"товар {label} материал номер {i}", "labels": [label],
                     "leakage_group": f"g{i}", "split": "train" if i < 40 else "validation" if i < 50 else "test"})
    return pd.DataFrame(rows)


def test_experiment_1_small_synthetic(monkeypatch, tmp_path):
    monkeypatch.setattr(exp1, "prepare_work_dataset", lambda *a, **k: synthetic_data())
    metrics = exp1.train(Path("x"), Path("y"), tmp_path / "exp1", True, max_features=1000)
    assert 0 <= metrics["micro_f1"] <= 1 and (tmp_path / "exp1/model.joblib").exists()


class MockEncoder:
    def encode(self, texts, **kwargs):
        return np.array([[len(x), x.count("tiling"), x.count("wall_painting")] for x in texts], dtype=float)


def test_experiment_2_mocked_embeddings(monkeypatch, tmp_path):
    monkeypatch.setattr(exp2, "prepare_work_dataset", lambda *a, **k: synthetic_data())
    metrics = exp2.train(Path("x"), Path("y"), tmp_path / "exp2", True, "mock", encoder=MockEncoder())
    assert metrics["embedding_model"] == "mock" and (tmp_path / "exp2/embeddings.npy").exists()
