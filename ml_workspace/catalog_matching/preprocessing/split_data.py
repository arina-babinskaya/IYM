from __future__ import annotations

import csv, hashlib, json, random
from collections import Counter, defaultdict
from pathlib import Path
from .catalog_parser import normalize_name

SEED = 20261029
RATIOS = {"train": .70, "validation": .15, "test": .15}

def duplicate_group(row: dict) -> str:
    # Conservative near-duplicate key removes punctuation, case and SKU-like numeric suffixes.
    name = normalize_name(row.get("name"))
    compact = " ".join(x for x in name.split() if not (x.isdigit() and len(x) >= 5))
    return hashlib.sha256(compact.encode()).hexdigest()[:20]

def assign_splits(rows: list[dict], seed: int = SEED) -> list[dict]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows): groups[duplicate_group(row)].append(i)
    rng = random.Random(seed)
    by_class: dict[str, list[tuple[str, list[int]]]] = defaultdict(list)
    for gid, indices in groups.items():
        labels = Counter(rows[i]["target_category_id"] for i in indices)
        by_class[labels.most_common(1)[0][0]].append((gid, indices))
    assignments = {}
    for label, items in sorted(by_class.items()):
        rng.shuffle(items); items.sort(key=lambda x: len(x[1]), reverse=True)
        totals = {k: 0 for k in RATIOS}; target = {k: sum(len(x[1]) for x in items)*v for k,v in RATIOS.items()}
        for gid, indices in items:
            split = min(RATIOS, key=lambda k: (totals[k] + len(indices) - target[k]) / max(target[k], 1))
            assignments[gid] = split; totals[split] += len(indices)
    result=[]
    for row in rows:
        out=dict(row); out["duplicate_group_id"]=duplicate_group(row); out["split"]=assignments[out["duplicate_group_id"]]; result.append(out)
    return result

def write_splits(rows: list[dict], output_dir: str | Path, seed: int = SEED) -> dict:
    output=Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    assigned=assign_splits(rows, seed); fields=list(assigned[0])
    checksums={}; counts={}
    for split in RATIOS:
        path=output/f"{split}.csv"; subset=[x for x in assigned if x["split"]==split]
        with path.open("w",newline="",encoding="utf-8") as fh:
            w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(subset)
        checksums[path.name]=hashlib.sha256(path.read_bytes()).hexdigest(); counts[split]=len(subset)
    manifest_path=output/"split_manifest.csv"
    with manifest_path.open("w",newline="",encoding="utf-8") as fh:
        fields2=["product_id","duplicate_group_id","split","target_category_id","mapping_status"]
        w=csv.DictWriter(fh,fieldnames=fields2); w.writeheader(); w.writerows({k:x[k] for k in fields2} for x in assigned)
    checksums[manifest_path.name]=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    metadata={"version":output.name,"seed":seed,"ratios":RATIOS,"counts":counts,"sha256":checksums,
              "eligible_only":True,"group_key":"sha256(normalized name without long numeric tokens)"}
    (output/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    return metadata

def validate_isolation(rows: list[dict]) -> None:
    seen_ids={}; seen_groups={}
    for row in rows:
        pid=row["product_id"]; gid=row["duplicate_group_id"]; split=row["split"]
        if pid in seen_ids: raise ValueError(f"duplicate product ID: {pid}")
        if gid in seen_groups and seen_groups[gid] != split: raise ValueError(f"group leakage: {gid}")
        seen_ids[pid]=split; seen_groups[gid]=split
