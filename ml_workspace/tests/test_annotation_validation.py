import json

import pandas as pd
import pytest

from validate_annotations import validate_file


def valid_row():
    return {"product_id": 1, "review_status": "reviewed", "reviewed_product_categories": '["furniture"]',
            "reviewed_work_types": "[]", "reviewed_room_types": '["living_room"]',
            "reviewed_usage_contexts": '["indoor"]', "reviewed_material_roles": "[]", "review_notes": "ok"}


def test_annotation_validation(tmp_path):
    path = tmp_path / "review.csv"
    pd.DataFrame([valid_row()]).to_csv(path, index=False)
    assert validate_file(path)[0].startswith("PASS")


def test_annotation_validation_rejects_bad_id(tmp_path):
    item = valid_row(); item["reviewed_room_types"] = '["mars"]'
    path = tmp_path / "bad.csv"; pd.DataFrame([item]).to_csv(path, index=False)
    with pytest.raises(ValueError):
        validate_file(path)
