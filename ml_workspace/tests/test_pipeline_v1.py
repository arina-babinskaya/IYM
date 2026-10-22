from pathlib import Path
import pandas as pd
from ml_workspace.ml_api import (load_data,prepare_features,train,validate,evaluate,save_model,load_model,predict)
from ml_workspace.ml_api.types import ProductInput,TrainingConfig
from ml_workspace.taxonomy.taxonomy_v2 import TAXONOMY_VERSION

ROOT=Path(__file__).resolve().parents[2]

def _balanced_bundle():
    data=load_data(ROOT/"ml_workspace/data/products_taxonomy_v2.csv")
    parts=[]
    for _,split in data.frame.groupby("split"):
        by_domain=pd.concat([g.head(8) for _,g in split.groupby("domain_label")])
        renovation=split[split.product_category.ne("")]
        by_category=pd.concat([g.head(3) for _,g in renovation.groupby("product_category")])
        parts.append(pd.concat([by_domain,by_category]).drop_duplicates("product_id"))
    data.frame=pd.concat(parts,ignore_index=True)
    return data

def test_end_to_end_roundtrip_single_and_batch(tmp_path):
    data=_balanced_bundle(); config=TrainingConfig(max_features=1000,logistic_max_iter=100)
    features=prepare_features(data,config); model=train(features,config); validation=validate(model,features); result=evaluate(model,features)
    out=tmp_path/"artifact"; save_model(model,out,validation,result); loaded=load_model(out,TAXONOMY_VERSION,trusted=True)
    one=predict(loaded,ProductInput(1,"Грунтовка для стен","Грунтовки",description="Для внутренних работ"))
    batch=predict(loaded,[ProductInput(2,"Семена огурца","Семена овощей"),ProductInput(3,"Кабель ВВГ","Кабель электрический")])
    assert one.product_id==1 and len(batch)==2 and set(loaded.metadata["fit_product_ids"])==set(features.fit_product_ids)
    assert loaded.feature_schema==model.feature_schema and "limitation" in result.metrics
