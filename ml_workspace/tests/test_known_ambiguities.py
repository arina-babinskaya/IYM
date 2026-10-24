import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def joined():
    p = pd.read_csv(ROOT / "ml_workspace/data/products_clean.csv", keep_default_na=False)
    l = pd.read_csv(ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv", keep_default_na=False)
    return p.merge(l, on="product_id")


def test_water_socket_not_electrical():
    data = joined()
    rows = data[data.name.str.contains("водорозет", case=False)]
    assert len(rows) and rows.proposed_work_types.map(lambda x: "electrical_fittings" not in json.loads(x)).all()


def test_enamel_duct_not_paint_and_cable_tie_not_screed():
    data = joined()
    ducts = data[data.name.str.contains("воздуховод.*эмаль", case=False, regex=True)]
    ties = data[data.name.str.contains("стяжка кабельная", case=False)]
    assert ducts.proposed_work_types.map(lambda x: "wall_painting" not in json.loads(x)).all()
    assert ties.proposed_work_types.map(lambda x: "floor_screed" not in json.loads(x)).all()


def test_garden_pipe_not_automatically_plumbing():
    data = joined()
    rows = data[data.name.str.contains("поддержки растений труба", case=False)]
    assert rows.proposed_work_types.map(lambda x: "plumbing_rough" not in json.loads(x)).all()


def test_work_multilabel_exists_and_primer_not_all_works():
    data = joined()
    assert data.proposed_work_types.map(lambda x: len(json.loads(x)) > 1).any()
    primers = data[data.name.str.contains("грунтовка", case=False)]
    assert primers.proposed_work_types.map(lambda x: len(json.loads(x)) <= 2).all()
