"""Generate deterministic v1→v2 coverage analysis and review samples."""
from __future__ import annotations
import csv, json, re
from collections import Counter, defaultdict
from pathlib import Path
from .taxonomy.catalog_taxonomy import CATEGORIES
from .preprocessing.weak_labeling import _COMPILED

ROOT=Path(__file__).parent
def read_csv(path):
    with path.open(encoding="utf-8") as f: return list(csv.DictReader(f))
def load_version(version):
    base=ROOT/f"data/{version}"; out={}
    for name in ("train","validation","test","review_queue"):
        for r in read_csv(base/f"{name}.csv"): out[r["product_id"]]=r
    return out
def patterns(names):
    c=Counter()
    for name in names:
        words=re.findall(r"[а-яёa-z]+",name.casefold())
        c.update([" ".join(words[:2])] if words else [])
    return "; ".join(f"{x} ({n})" for x,n in c.most_common(3))
def main():
    v1,v2=load_version("splits_v1"),load_version("splits_v2"); assert set(v1)==set(v2)
    transitions=[]
    for pid in sorted(v1,key=lambda x:(len(x),x)):
        a,b=v1[pid],v2[pid]
        transitions.append({"product_id":pid,"previous_status":a["mapping_status"],"new_status":b["mapping_status"],"previous_target":a["target_category_id"],"new_target":b["target_category_id"],"changed":a["target_category_id"]!=b["target_category_id"]})
    summary={
      "products":len(v2), "v1_status":dict(Counter(x["mapping_status"] for x in v1.values())),
      "v2_status":dict(Counter(x["mapping_status"] for x in v2.values())),
      "newly_resolved":sum(v1[p]["mapping_status"]!="confident" and v2[p]["mapping_status"]=="confident" for p in v1),
      "labels_changed":sum(x["changed"] for x in transitions),
      "confident_moved":sum(v1[p]["mapping_status"]=="confident" and v2[p]["mapping_status"]=="confident" and v1[p]["target_category_id"]!=v2[p]["target_category_id"] for p in v1),
      "previously_confident_invalidated":sum(v1[p]["mapping_status"]=="confident" and v2[p]["mapping_status"]!="confident" for p in v1),
      "v1_category_support":dict(sorted(Counter(x["target_category_id"] for x in v1.values() if x["mapping_status"]=="confident").items())),
      "v2_category_support":dict(sorted(Counter(x["target_category_id"] for x in v2.values() if x["mapping_status"]=="confident").items())),
    }
    (ROOT/"reports/coverage_transition_v2.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    with (ROOT/"reports/taxonomy_audit_v2.csv").open("w",newline="",encoding="utf-8") as f:
        fields=["category_id","category_name","parent_id","definition_inclusion","exclusion","v1_support","v2_support","neighboring_categories","granularity","audit_note"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for cat in CATEGORIES:
            neighbors=[x.id for x in CATEGORIES if x.parent_id==cat.parent_id and x.id!=cat.id]
            support=summary["v2_category_support"].get(cat.id,0)
            w.writerow({"category_id":cat.id,"category_name":cat.name,"parent_id":cat.parent_id,"definition_inclusion":cat.definition,"exclusion":cat.excludes,"v1_support":summary["v1_category_support"].get(cat.id,0),"v2_support":support,"neighboring_categories":" | ".join(neighbors),"granularity":"leaf; single-label target","audit_note":"low support; review before training" if 0<support<30 else ("operational review-only leaf" if cat.id=="review.unresolved" else "retained")})
    unresolved=defaultdict(list)
    for r in v2.values():
        if r["mapping_status"]!="confident": unresolved[(r["source_category_id"],r["source_category_name"])].append(r)
    fields=["source_category_id","source_category_name","product_count","status_counts","common_name_patterns","source_hierarchy","representative_examples","candidate_existing_categories","failure_reason"]
    with (ROOT/"reports/unresolved_source_categories_v2.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for (sid,sname),rows in sorted(unresolved.items(),key=lambda x:(-len(x[1]),x[0][1])):
            explicit=[c for x in rows for c in x.get("candidate_category_ids","").split("|") if c]
            # Candidate-only diagnostic: never used as a weak target.
            name_candidates=[]
            for x in rows[:50]:
                evidence=" ".join([x["name"],x.get("description","")])
                name_candidates.extend(cid for cid,rx,_ in _COMPILED if rx.search(evidence))
            candidates=list(dict.fromkeys(explicit+[x for x,_ in Counter(name_candidates).most_common(5)]))
            w.writerow({"source_category_id":sid,"source_category_name":sname,"product_count":len(rows),"status_counts":json.dumps(Counter(x["mapping_status"] for x in rows),ensure_ascii=False),"common_name_patterns":patterns([x["name"] for x in rows]),"source_hierarchy":"not available in export (single flat category)","representative_examples":" || ".join(x["name"] for x in rows[:3]),"candidate_existing_categories":" | ".join(candidates),"failure_reason":Counter(x["review_reason"] for x in rows).most_common(1)[0][0]})
    # Deterministic, stratified review sample. This is not ground truth.
    buckets=defaultdict(list)
    support=Counter(x["target_category_id"] for x in v2.values() if x["mapping_status"]=="confident")
    for pid,b in v2.items():
        a=v1[pid]
        if a["mapping_status"]!="confident" and b["mapping_status"]=="confident": buckets["newly_resolved"].append((a,b))
        if b.get("mapping_method")=="product_override": buckets["product_override"].append((a,b))
        if a["mapping_status"]=="ambiguous" and b["mapping_status"]=="confident": buckets["previously_ambiguous"].append((a,b))
        if b["mapping_status"]!="confident": buckets["remaining_review"].append((a,b))
        if b["mapping_status"]=="confident" and support[b["target_category_id"]]<100: buckets["rare_category"].append((a,b))
        if b["mapping_status"]=="confident" and support[b["target_category_id"]]>2000: buckets["broad_category"].append((a,b))
    chosen=[]; seen=set()
    for bucket,limit in (("product_override",25),("previously_ambiguous",25),("newly_resolved",35),("rare_category",15),("broad_category",15),("remaining_review",25)):
        for a,b in sorted(buckets[bucket],key=lambda x:x[1]["product_id"]):
            if b["product_id"] in seen: continue
            seen.add(b["product_id"]); chosen.append((bucket,a,b))
            if sum(x[0]==bucket for x in chosen)>=limit: break
    fields=["audit_stratum","product_id","name","source_category_id","source_category_name","previous_target_category_id","previous_status","proposed_target_category_id","new_status","mapping_method","labeling_rule_id","mapping_evidence","review_note"]
    with (ROOT/"reports/label_audit_sample_v2.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for bucket,a,b in chosen:w.writerow({"audit_stratum":bucket,"product_id":b["product_id"],"name":b["name"],"source_category_id":b["source_category_id"],"source_category_name":b["source_category_name"],"previous_target_category_id":a["target_category_id"],"previous_status":a["mapping_status"],"proposed_target_category_id":b["target_category_id"],"new_status":b["mapping_status"],"mapping_method":b.get("mapping_method",""),"labeling_rule_id":b["labeling_rule_id"],"mapping_evidence":b.get("mapping_evidence",""),"review_note":"REVIEW SAMPLE — not human-verified ground truth"})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
