"""Build weak labels, source mapping audit and leakage-safe supervised splits."""
from __future__ import annotations

import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path
from .preprocessing.catalog_parser import iter_products, inspection_row
from .preprocessing.weak_labeling import label_dict
from .preprocessing.split_data import write_splits
from .taxonomy.catalog_taxonomy import snapshot

def build(catalog: Path, output: Path, mapping_csv: Path) -> dict:
    all_rows=[]; mapping=defaultdict(lambda: Counter()); mapping_samples={}
    for product in iter_products(catalog):
        row=inspection_row(product); label=label_dict(product); row.update(label); all_rows.append(row)
        mapping[(row["source_category_id"],row["source_category_name"])][(label["target_category_id"],label["mapping_status"],label["labeling_rule_id"])]+=1
        mapping_samples.setdefault((row["source_category_id"],label["target_category_id"],label["labeling_rule_id"]),label)
    mapping_csv.parent.mkdir(parents=True,exist_ok=True)
    with mapping_csv.open("w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(["source_category_id","source_category_name","target_category_id","mapping_status","labeling_rule_id","mapping_method","mapping_evidence","product_count"])
        for (sid,sname), targets in sorted(mapping.items(),key=lambda x:x[0][1]):
            for (target,status,rule),count in targets.items():
                sample=mapping_samples[(sid,target,rule)]
                w.writerow([sid,sname,target,status,rule,sample["mapping_method"],sample["mapping_evidence"],count])
    eligible=[x for x in all_rows if x["supervised_eligible"]]
    output.mkdir(parents=True,exist_ok=True)
    taxonomy=snapshot()
    (output/"taxonomy_snapshot.json").write_text(json.dumps(taxonomy,ensure_ascii=False,indent=2),encoding="utf-8")
    metadata=write_splits(eligible,output)
    metadata["taxonomy_version"]=taxonomy["version"]
    (output/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    stats={"catalog_products":len(all_rows),"supervised_eligible":len(eligible),"review_required":len(all_rows)-len(eligible),
           "status_counts":Counter(x["mapping_status"] for x in all_rows),"class_counts":Counter(x["target_category_id"] for x in eligible),"splits":metadata}
    (output/"coverage.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
    review=output/"review_queue.csv"
    review_fields=list(all_rows[0])
    with review.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=review_fields); w.writeheader(); w.writerows(x for x in all_rows if not x["supervised_eligible"])
    return stats

def main():
    p=argparse.ArgumentParser(); p.add_argument("--catalog",default="requirments/products_final.json"); p.add_argument("--output",default="ml_workspace/catalog_matching/data/splits_v1"); p.add_argument("--mapping",default="ml_workspace/catalog_matching/taxonomy/source_category_mapping.csv")
    a=p.parse_args(); print(json.dumps(build(Path(a.catalog),Path(a.output),Path(a.mapping)),ensure_ascii=False,indent=2))
if __name__ == "__main__": main()
