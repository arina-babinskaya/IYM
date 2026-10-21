import argparse
import json
from collections import Counter

from app.api.deps import get_classifier
from app.db import get_sessionmaker
from app.models import Product
from app.taxonomy import WORKS, WorkType


def f1(tp: int, fp: int, fn: int) -> float:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def evaluate(gold: list[dict]) -> dict:
    clf = get_classifier()
    tp, fp, fn = Counter(), Counter(), Counter()
    material_hits, errors = 0, []
    with get_sessionmaker()() as session:
        for row in gold:
            product = session.get(Product, row["id"])
            if product is None:
                errors.append({"id": row["id"], "error": "нет в базе"})
                continue
            s = clf.predict([product])[0]
            pred, true = {w.value for w in s.work_types}, set(row["work_types"])
            for w in pred & true:
                tp[w] += 1
            for w in pred - true:
                fp[w] += 1
            for w in true - pred:
                fn[w] += 1
            material_hits += s.material.value == row.get("material")
            if pred != true:
                errors.append({"id": row["id"], "name": product.name, "expected": sorted(true), "predicted": sorted(pred)})
    labels = sorted(set(tp) | set(fp) | set(fn))
    per_work = {w: round(f1(tp[w], fp[w], fn[w]), 3) for w in labels}
    return {
        "items": len(gold),
        "micro_f1": round(f1(sum(tp.values()), sum(fp.values()), sum(fn.values())), 3),
        "macro_f1": round(sum(per_work.values()) / len(per_work), 3) if per_work else 0.0,
        "material_accuracy": round(material_hits / len(gold), 3) if gold else 0.0,
        "per_work_f1": per_work,
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="mock_catalog/sample_gold.jsonl")
    args = ap.parse_args()
    gold = [json.loads(line) for line in open(args.gold, encoding="utf-8") if line.strip()]
    res = evaluate(gold)
    print(f"Товаров: {res['items']}  micro-F1: {res['micro_f1']}  macro-F1: {res['macro_f1']}  "
          f"точность материала: {res['material_accuracy']}")
    for w, v in sorted(res["per_work_f1"].items(), key=lambda x: x[1]):
        print(f"  {v:5.3f}  {WORKS[WorkType(w)].title}")
    for e in res["errors"]:
        print("  ошибка:", json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
