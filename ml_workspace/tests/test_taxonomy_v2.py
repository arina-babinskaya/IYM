import pytest
from ml_workspace.scripts.weak_labeling_v2 import label_product
from ml_workspace.taxonomy.taxonomy_v2 import WORK_IDS,PRODUCT_CATEGORIES,stages_for_work_types
from ml_workspace.ml_api.backend_adapter import WorkTypeInferenceAdapter
from ml_workspace.ml_api.types import Prediction

def row(name,category,description="",characteristics="[]"):
 return {"name":name,"source_category":category,"description_clean":description,"marketing_description_clean":"","important_attributes_json":"{}","characteristics_json":characteristics}

@pytest.mark.parametrize("product,work,category",[
 (row("Кабель ВВГнг 3x2,5","Кабель электрический в бухтах"),"electrical_wiring","electrical_goods"),
 (row("Труба PPR 20 мм","Трубы"),"plumbing_rough","plumbing"),
 (row("Воздуховод круглый","Воздуховоды"),"ventilation_install","ventilation"),
 (row("Радиатор секционный","Радиаторы секционные"),"heating_climate_install","heating_climate"),
])
def test_engineering_real_categories(product,work,category):
 result=label_product(product); assert result["domain_label"]=="renovation" and work in result["work_types"] and result["product_category"]==category

@pytest.mark.parametrize("category",["Биты","Буры","Коронки","Пилки для лобзиков и эл. ножовок","Диски отрезные абразивные"])
def test_clear_tool_accessory_not_unknown(category):
 result=label_product(row("Оснастка",category)); assert result["domain_label"]=="renovation" and result["product_category"]=="tool_accessories"

def test_ppe_and_generic_tool_behavior():
 assert label_product(row("Респиратор FFP2","Респираторы, защитные маски"))["product_category"]=="protective_equipment"
 result=label_product(row("Универсальный инструмент","Инструменты")); assert len(result["work_types"])<=1

def test_furnishing_is_not_sixth_stage():
 result=label_product(row("Кровать Гавана","Кровати для спальни"))
 assert result["domain_label"]=="furnishing" and result["activities"]==["room_furnishing"]
 assert result["renovation_stages"]==[] and result["work_types"]==[] and "bedroom" in result["room_types"]

def test_decor_distinctions():
 mounted=label_product(row("Панель декоративная","Декоративные стеновые панели")); assert "decorative_finish_install" in mounted["work_types"]
 placed=label_product(row("Репродукция","Репродукции")); assert placed["domain_label"]=="furnishing" and placed["product_category"]=="decorative_objects"
 assert label_product(row("Стакан","Стаканы"))["domain_label"]=="non_renovation"

def test_known_ambiguities_v2():
 assert "electrical_fittings" not in label_product(row("Водорозетка","Фитинги"))["work_types"]
 assert "wall_painting" not in label_product(row("Воздуховод эмалированный","Воздуховоды"))["work_types"]
 assert "floor_screed" not in label_product(row("Стяжка кабельная","Стяжки кабельные"))["work_types"]
 assert "plumbing_rough" not in label_product(row("Шланг поливочный","Шланги для полива"))["work_types"]
 assert label_product(row("Семена огурца","Семена овощей"))["domain_label"]=="non_renovation"
 assert label_product(row("Деталь X","Прочее"))["domain_label"]=="unknown_needs_review"

def test_taxonomy_ids_and_stages():
 assert len(WORK_IDS)==len(set(WORK_IDS))==20 and len(PRODUCT_CATEGORIES)==len(set(PRODUCT_CATEGORIES))
 assert stages_for_work_types(["ventilation_install"])==["rough_work","final_stage"]
 with pytest.raises(ValueError): stages_for_work_types(["bad_id"])

def test_backend_compatibility_is_explicit():
 prediction=Prediction(1,["plumbing_fixture_install","ventilation_install"],{"plumbing_fixture_install":.9,"ventilation_install":.8},"predicted",domain_label="renovation",work_types=["plumbing_fixture_install","ventilation_install"],activities=["renovation"])
 result=WorkTypeInferenceAdapter.to_backend_suggestion(prediction)
 assert "plumbing_install" in result["work_types"]
 assert result["flags"]["unsupported_taxonomy_v2_work_types"]==["ventilation_install"]
