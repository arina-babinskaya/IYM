"""Сборка taxonomy_v2 labels и task-specific CSV при неизменном split manifest."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd
from ml_workspace.ml_api.feature_schema import FEATURE_COLUMNS,build_input_text
from ml_workspace.scripts.build_taxonomy_v1_dataset import duplicate_group,SEED
from ml_workspace.scripts.weak_labeling_v2 import label_product,serialize_labels
from ml_workspace.taxonomy.taxonomy_v2 import *

ROOT=Path(__file__).resolve().parents[2]; DATA=ROOT/"ml_workspace/data"; SPLITS=DATA/"splits_v2"; TAX=ROOT/"ml_workspace/taxonomy"; REPORTS=ROOT/"ml_workspace/reports"
def file_sha(path:Path)->str:
 h=hashlib.sha256();
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
 return h.hexdigest()
def write_taxonomy()->None:
 pd.DataFrame(STAGES).to_csv(TAX/"renovation_stages_v2.csv",index=False)
 rows=[]
 for wid,name,desc,stages in WORK_TYPES:
  rows.append({"taxonomy_version":TAXONOMY_VERSION,"work_type_id":wid,"ru_name":name,"definition":desc,"renovation_stages":json.dumps(stages,ensure_ascii=False),"material_roles":json.dumps(WORK_ROLE_MAP[wid],ensure_ascii=False),"inclusion_criteria":"Явное назначение в retailer category, имени или технических характеристиках.","exclusion_criteria":"Омоним, садовое/автомобильное/бытовое применение или недостаточный контекст.","representative_products": {"ventilation_install":"воздуховод, вентиляционная решётка, вытяжной вентилятор","heating_climate_install":"радиатор, комплект тёплого пола, котёл"}.get(wid,f"Материал или инструмент для операции «{name}»"),"ambiguous_examples":"Универсальные инструменты без назначения не получают work type.","backend_relationship":"same" if wid not in {"ventilation_install","heating_climate_install"} else "new_not_in_backend"})
 pd.DataFrame(rows).to_csv(TAX/"work_types_v2.csv",index=False)
 pd.DataFrame({"taxonomy_version":TAXONOMY_VERSION,"product_category_id":PRODUCT_CATEGORIES,"single_label":True}).to_csv(TAX/"product_categories_v2.csv",index=False)
 pd.DataFrame(ACTIVITIES).to_csv(TAX/"activities_v2.csv",index=False)
 pd.DataFrame({"room_type_id":ROOM_TYPES,"multi_label":True}).to_csv(TAX/"room_types_v2.csv",index=False)
 pd.DataFrame([{"work_type_id":w,"renovation_stages":json.dumps(s)} for w,s in WORK_TO_STAGES.items()]).to_csv(TAX/"work_type_to_stage_v2.csv",index=False)
 pd.DataFrame([{"v1_id":k,"v2_id":v,"compatibility":"same_or_split"} for k,v in V1_TO_V2.items()]).to_csv(TAX/"taxonomy_v1_to_v2_mapping.csv",index=False)
def main()->None:
 write_taxonomy(); clean=pd.read_csv(DATA/"products_clean.csv",keep_default_na=False,low_memory=False)
 generated=pd.DataFrame([serialize_labels(label_product(r)) for _,r in clean.iterrows()]); master=pd.concat([clean.reset_index(drop=True),generated],axis=1)
 master["input_text"]=[build_input_text(r) for r in clean.to_dict("records")]; master["structured_input_features"]=clean[FEATURE_COLUMNS].apply(lambda r:json.dumps(r.to_dict(),ensure_ascii=False,sort_keys=True),axis=1)
 master["duplicate_group"]=master.apply(duplicate_group,axis=1)
 manifest_path=DATA/"splits/split_manifest.csv"; before_hash=file_sha(manifest_path); manifest=pd.read_csv(manifest_path,dtype={"duplicate_group":"string"})
 check=master[["product_id","duplicate_group"]].merge(manifest[["product_id","duplicate_group","split"]],on="product_id",suffixes=("_new","_old"),validate="one_to_one")
 if len(check)!=len(master) or (check.duplicate_group_new!=check.duplicate_group_old).any(): raise RuntimeError("taxonomy_v2 cannot reuse manifest: source IDs/groups changed")
 master["split"]=master.product_id.map(manifest.set_index("product_id").split)
 master["domain_valid"]=master.domain_status.eq("known"); master["activity_valid"]=master.activity_status.eq("known")
 master["product_category_valid"]=master.product_category_status.eq("known"); master["work_types_valid"]=master.work_types_status.eq("known"); master["room_types_valid"]=master.room_types_status.eq("known") & master.domain_label.eq("furnishing")
 if file_sha(manifest_path)!=before_hash: raise RuntimeError("Existing manifest was modified")
 columns=["product_id","cod_good","name","source_category","category_names","description_clean","marketing_description_clean","important_attributes_json","characteristics_json","brand_name","sale_unit","price","characteristic_count","information_completeness","input_text","structured_input_features","domain_label","activities","product_category","work_types","renovation_stages","room_types","material_roles","domain_valid","activity_valid","product_category_valid","work_types_valid","room_types_valid","label_confidence","label_evidence","label_conflicts","label_status","labeling_method","taxonomy_version","duplicate_group","split"]
 master[columns].to_csv(DATA/"products_taxonomy_v2.csv",index=False); SPLITS.mkdir(parents=True,exist_ok=True)
 for split in ("train","validation","test"): master.loc[master.split.eq(split),columns].to_csv(SPLITS/f"{split}.csv",index=False)
 manifest.to_csv(SPLITS/"split_manifest_reused.csv",index=False)
 support=[]
 for split,part in master.groupby("split"):
  for target,classes,valid in (("domain",["renovation","furnishing","non_renovation"],"domain_valid"),("activities",[x["id"] for x in ACTIVITIES],"activity_valid"),("product_category",PRODUCT_CATEGORIES,"product_category_valid"),("work_types",WORK_IDS,"work_types_valid"),("room_types",ROOM_TYPES,"room_types_valid")):
   for c in classes:
    if target in {"activities","work_types","room_types"}: n=int(part.loc[part[valid],target].map(lambda x,c=c:c in json.loads(x)).sum())
    else:
     column="domain_label" if target=="domain" else target
     n=int((part[valid]&part[column].eq(c)).sum())
    support.append({"split":split,"target":target,"class":c,"support":n,"valid_rows":int(part[valid].sum())})
 pd.DataFrame(support).to_csv(SPLITS/"class_support.csv",index=False)
 old=pd.read_csv(DATA/"products_taxonomy_v1.csv",usecols=["product_id","domain_label","product_category","work_types"],keep_default_na=False).rename(columns={c:f"v1_{c}" for c in ["domain_label","product_category","work_types"]})
 changed=master[["product_id","name","source_category","domain_label","activities","product_category","work_types","label_evidence","split"]].merge(old,left_on="product_id",right_on="product_id")
 changed=changed[(changed.v1_domain_label!=changed.domain_label)|(changed.v1_product_category!=changed.product_category)|(changed.v1_work_types!=changed.work_types)]
 changed.to_csv(REPORTS/"taxonomy_v1_to_v2_changed_products.csv",index=False)
 stats={"taxonomy_version":TAXONOMY_VERSION,"rows":len(master),"manifest_sha256":before_hash,"domain":master.domain_label.value_counts().to_dict(),"splits":master.split.value_counts().to_dict(),"unknown":int(master.domain_label.eq("unknown_needs_review").sum()),"moved_from_v1_unknown":int(changed.v1_domain_label.eq("unknown_needs_review").sum()),"changed_rows":len(changed),"multi_work_rows":int(master.work_types.map(lambda x:len(json.loads(x))>1).sum()),"valid_rows":{c:int(master[c].sum()) for c in ["domain_valid","activity_valid","product_category_valid","work_types_valid","room_types_valid"]}}
 (REPORTS/"dataset_statistics_v2.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(stats,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
