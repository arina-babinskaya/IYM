import pandas as pd

from prepare_extended_labels import classify_family, classify_multilabel
from taxonomy_config import ROOM_RULES, USAGE_RULES


def row(name, category, description="", characteristics="{}", complete=True):
    return pd.Series({"name": name, "source_category": category, "description_clean": description,
                      "marketing_description_clean": "", "important_attributes_json": characteristics,
                      "has_description": bool(description), "has_marketing_description": False,
                      "has_characteristics": complete})


def test_product_family_furniture_and_barbecue():
    assert classify_family(row("стул обеденный", "Стулья для столовой"))["primary"] == "furniture"
    result = classify_family(row("щепа для копчения", "Щепа для копчения"))
    assert result["primary"] == "barbecue_grilling" and result["labels"] == ["garden_outdoor", "barbecue_grilling"]


def test_multilabel_rooms_are_evidence_based():
    item = row("стул кухонный обеденный", "Стулья для столовой", "Для кухни и столовой")
    result = classify_multilabel(item, ROOM_RULES, "room_type", "furniture")
    assert {"kitchen", "dining_room"} <= set(result["labels"])


def test_usage_insect_and_outdoor():
    item = row("уличная антимоскитная лампа", "Ловушки и отпугиватели насекомых", "для сада")
    result = classify_multilabel(item, USAGE_RULES, "usage_context", "pest_protection")
    assert "insect_protection" in result["labels"] and "garden" in result["labels"]


def test_other_and_unknown_are_distinct():
    known = classify_family(row("корм для кошек", "Корм для кошек", "Полнорационный корм"))
    incomplete = classify_family(row("неизвестный товар", "Прочее", complete=False))
    assert known["primary"] == "other"
    assert incomplete["primary"] == "unknown"
