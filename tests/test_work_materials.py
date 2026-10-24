import pytest

from app.taxonomy import WORKS, WorkType
from app.work_materials import ITEM_MATERIALS, NOT_IN_ESTIMATE_ROLES, derive

reference = pytest.importorskip("ml_workspace.taxonomy.work_type_materials_v2").WORK_TYPE_MATERIALS


def test_reference_covers_all_work_types():
    assert set(reference) == {w.value for w in WorkType}


def test_every_purchasable_item_is_mapped():
    missing = [i["item"] for items in reference.values() for i in items
               if i["role"] not in NOT_IN_ESTIMATE_ROLES and i["item"] not in ITEM_MATERIALS]
    assert missing == []


def test_backend_materials_match_reference():
    assert derive(reference) == {w: info.materials for w, info in WORKS.items()}
