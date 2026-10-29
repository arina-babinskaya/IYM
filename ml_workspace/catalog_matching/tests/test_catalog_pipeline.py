import csv, json
from pathlib import Path
import pytest

from ml_workspace.catalog_matching.taxonomy.catalog_taxonomy import CATEGORIES, CATEGORY_BY_ID, snapshot
from ml_workspace.catalog_matching.preprocessing.weak_labeling import label_product, feature_text
from ml_workspace.catalog_matching.preprocessing.split_data import assign_splits, validate_isolation

def product(name="Товар", category="Обои", cid="1"):
    return {"id":cid,"cod_good":cid,"name":name,"categories":{cid:category},"description":"Описание","marketing_description":"","characteristics":[]}

def test_taxonomy_complete_and_unique():
    assert len(CATEGORIES) == len({x.id for x in CATEGORIES})
    assert all(x.name and x.definition and x.parent_id and x.excludes for x in CATEGORIES)
    assert "review.unresolved" in CATEGORY_BY_ID

def test_single_label_and_provenance():
    result=label_product(product())
    assert result.target_category_id == "finishing.wallpaper"
    assert result.mapping_status == "confident" and result.labeling_rule_id.startswith("source.")
    assert isinstance(result.target_category_id,str) and "|" not in result.target_category_id

def test_invalid_and_ambiguous_products():
    assert label_product(product(category="Неизвестная группа")).supervised_eligible is False
    conflict=label_product(product(category="Садовые светильники и розетки"))
    assert conflict.mapping_status == "ambiguous" and not conflict.supervised_eligible

def test_no_target_leakage_features():
    row={"name":"Дрель","description":"аккумуляторная","target_category_id":"SECRET","source_category_name":"LEAK","labeling_rule_id":"LEAK2"}
    assert feature_text(row,"name") == "Дрель"
    assert "SECRET" not in feature_text(row,"name_description") and "LEAK" not in feature_text(row,"name_description")

def test_reproducible_group_isolated_splits():
    rows=[]
    for i in range(60): rows.append({"product_id":str(i),"name":f"товар {i//2}","target_category_id":"a" if i<30 else "b","mapping_status":"confident"})
    a=assign_splits(rows); b=assign_splits(rows)
    assert [(x["product_id"],x["split"]) for x in a] == [(x["product_id"],x["split"]) for x in b]
    validate_isolation(a)
    groups={}
    for x in a:
        assert groups.setdefault(x["duplicate_group_id"],x["split"]) == x["split"]

def test_duplicate_product_id_rejected():
    with pytest.raises(ValueError): validate_isolation([{"product_id":"1","duplicate_group_id":"a","split":"train"},{"product_id":"1","duplicate_group_id":"b","split":"test"}])

def test_source_mapping_file_covers_rows():
    path=Path(__file__).parents[1]/"taxonomy/source_category_mapping.csv"
    with path.open(encoding="utf-8") as fh: rows=list(csv.DictReader(fh))
    assert len(rows) >= 2375
    assert all(x["target_category_id"] in CATEGORY_BY_ID for x in rows)

def test_snapshot_serializable(): json.dumps(snapshot(),ensure_ascii=False)

@pytest.mark.parametrize("cid,source,name,expected,method",[
    ("2269","Столешницы ДСП","столешница 1200х600мм","furniture.kitchen","product_override"),
    ("4106","Стеновые панели","панель кухонная Камень 244х61см МДФ","finishing.decor","product_override"),
    ("9999","Ножницы","ножницы для живой изгороди 550мм","garden.tools","product_override"),
    ("626","Подставки для цветов","подставка для цветов металлическая","garden.accessories","product_override"),
    ("4016","Кисти малярные","кисть плоская 50мм","finishing.painting_tools","exact_source_id"),
    ("3280","Шампуни для волос","шампунь 400мл","personal_care.hygiene","exact_source_id"),
])
def test_v2_regression_families(cid,source,name,expected,method):
    result=label_product(product(name=name,category=source,cid=cid))
    assert result.target_category_id==expected and result.mapping_method==method

def test_mapping_is_deterministic():
    p=product(name="панель кухонная МДФ",category="Стеновые панели",cid="4106")
    assert label_product(p)==label_product(p)

def test_v2_split_metadata_and_notebook_compatibility():
    root=Path(__file__).parents[1]
    meta=json.loads((root/"data/splits_v2/metadata.json").read_text())
    tax=json.loads((root/"data/splits_v2/taxonomy_snapshot.json").read_text())
    notebook=json.loads((root/"notebooks/train_catalog_classifier_colab.ipynb").read_text())
    assert meta["version"]=="splits_v2" and meta["taxonomy_version"]==tax["version"]
    assert "SPLIT_VERSION" in json.dumps(notebook)
