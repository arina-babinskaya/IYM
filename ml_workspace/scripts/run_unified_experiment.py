#!/usr/bin/env python3
"""CLI for all unified work-type experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml_workspace"))

from ml_api import (TrainingConfig, evaluate, load_data, prepare_features,
                    save_model, train, validate)
from ml_api.reporting import save_evaluation_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", choices=["tfidf_logreg", "embeddings_logreg", "catboost_structured"], required=True)
    parser.add_argument("--label-policy", choices=["reviewed_only", "weak_only", "reviewed_plus_weak"], default="reviewed_only")
    parser.add_argument("--clean", type=Path, default=ROOT / "ml_workspace/data/products_clean.csv")
    parser.add_argument("--weak-labels", type=Path, default=ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv")
    parser.add_argument("--reviewed", type=Path, nargs="*", default=[ROOT / "ml_workspace/data/manual_review_500.csv"])
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "ml_workspace/taxonomy/work_types_draft.csv")
    parser.add_argument("--split-manifest", type=Path, default=ROOT / "ml_workspace/data/work_type_split_manifest.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--max-features", type=int, default=80000)
    parser.add_argument("--catboost-iterations", type=int, default=100)
    args = parser.parse_args()
    config = TrainingConfig(experiment=args.experiment, random_seed=args.seed, max_features=args.max_features,
                            catboost_iterations=args.catboost_iterations, use_gpu=args.gpu)
    data = load_data(args.clean, args.weak_labels, args.reviewed, args.split_manifest, args.taxonomy,
                     "work_types_draft_v2", args.label_policy, args.seed)
    features = prepare_features(data, config, cache_dir=ROOT / "ml_workspace/cache")
    model = train(features, config)
    validation = validate(model, features)
    result = evaluate(model, features)
    save_model(model, args.output, validation, result)
    save_evaluation_outputs(result, model, args.output / "evaluation")
    print(json.dumps({"experiment": args.experiment, "label_policy": args.label_policy,
                      "label_provenance": result.label_provenance, **result.metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
