import json
import pandas as pd
import pytest
from ml_workspace.scripts.weak_labeling_v1 import label_product
from ml_workspace.taxonomy.taxonomy_v1 import WORK_IDS, WORK_TO_STAGES, stages_for_work_types

def row(name,category,description=""):
    return {"name":name,"source_category":category,"description_clean":description,"marketing_description_clean":"","important_attributes_json":"{}","characteristics_json":"[]"}

def test_taxonomy_consistency_and_stage_derivation():
    assert len(WORK_IDS)==len(set(WORK_IDS))==18
    assert set(WORK_IDS)==set(WORK_TO_STAGES)
    assert stages_for_work_types(["wall_putty","wall_painting"])==["white_finish","finish_work"]
    with pytest.raises(ValueError): stages_for_work_types(["invented"])

@pytest.mark.parametrize("product,domain",[(row("Семена огурца","Семена овощей"),"non_renovation"),(row("Нечто X","Неизвестная"),"unknown_needs_review")])
def test_domain(product,domain):
    result=label_product(product); assert result["domain_label"]==domain
    if domain=="non_renovation": assert result["work_types"]==result["renovation_stages"]==[]

def test_known_ambiguities_and_multilabel():
    assert "electrical_fittings" not in label_product(row("Водорозетка","Фитинги"))["work_types"]
    assert "wall_painting" not in label_product(row("Воздуховод эмалированный","Воздуховоды"))["work_types"]
    assert "floor_screed" not in label_product(row("Стяжка кабельная","Стяжки кабельные"))["work_types"]
    assert "plumbing_rough" not in label_product(row("Шланг для полива","Шланги садовые"))["work_types"]
    result=label_product(row("Грунтовка под покраску стен","Грунтовки","Для грунтования перед интерьерной краской"))
    assert "priming" in result["work_types"] and len(result["work_types"])<=2

def test_tools_and_ppe_in_scope():
    assert label_product(row("Шпатель строительный","Шпатели"))["domain_label"]=="renovation"
    assert label_product(row("Респиратор строительный","Средства защиты"))["product_category"]=="protective_equipment"
