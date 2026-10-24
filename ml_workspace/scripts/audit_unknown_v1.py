"""Воспроизводимый аудит unknown taxonomy_v1 без обучения модели."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]; DATA=ROOT/"ml_workspace/data"; REPORTS=ROOT/"ml_workspace/reports"
SEED=20261022

def sha(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def main()->None:
    data=pd.read_csv(DATA/"products_taxonomy_v1.csv",keep_default_na=False,low_memory=False)
    unknown=data[data.domain_label.eq("unknown_needs_review")].copy()
    top=unknown.source_category.value_counts().head(30).rename_axis("source_category").reset_index(name="count")
    top["share_unknown"]=top["count"]/len(unknown)
    top.to_csv(REPORTS/"unknown_top30_categories_v1.csv",index=False)
    sample=unknown.sample(n=min(100,len(unknown)),random_state=SEED).sort_values("product_id")
    columns=["product_id","cod_good","split","name","source_category","category_names","description_clean",
        "marketing_description_clean","important_attributes_json","characteristics_json","information_completeness",
        "characteristic_count","label_status","label_confidence","label_evidence","label_conflicts","taxonomy_version"]
    sample[columns].to_csv(REPORTS/"unknown_sample_100_v1.csv",index=False)
    summary={"seed":SEED,"unknown_count":len(unknown),"statuses":unknown.label_status.value_counts().to_dict(),
        "splits":unknown.split.value_counts().to_dict(),"manifest_sha256":sha(DATA/"splits/split_manifest.csv"),
        "sample_product_ids":sample.product_id.astype(int).tolist(),"top30":top.to_dict("records")}
    (REPORTS/"unknown_audit_machine_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k!="sample_product_ids" and k!="top30"},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
