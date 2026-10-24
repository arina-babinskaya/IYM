import json
from pathlib import Path
import pandas as pd
import pytest
from ml_workspace.ml_api import load_data, prepare_features
from ml_workspace.ml_api.feature_schema import FEATURE_COLUMNS, FORBIDDEN_COLUMNS, build_input_text, validate_feature_schema
from ml_workspace.ml_api.types import TrainingConfig

ROOT=Path(__file__).resolve().parents[2]

def test_feature_allowlist_rejects_targets_and_unknown():
    validate_feature_schema(FEATURE_COLUMNS)
    with pytest.raises(ValueError): validate_feature_schema(FEATURE_COLUMNS+["work_types"])
    with pytest.raises(ValueError): validate_feature_schema(FEATURE_COLUMNS+["new_silent_column"])

def test_text_ignores_generated_annotations():
    base={c:"source" for c in FEATURE_COLUMNS}; before=build_input_text(base)
    base.update({"work_types":"SECRET_TARGET","label_evidence":"SECRET_RULE","product_id":999})
    assert build_input_text(base)==before and "SECRET" not in before

def test_split_integrity_and_duplicate_groups():
    manifest=pd.read_csv(ROOT/"ml_workspace/data/splits/split_manifest.csv")
    assert manifest.product_id.is_unique
    assert manifest.groupby("duplicate_group").split.nunique().max()==1
    sets={s:set(manifest.loc[manifest.split.eq(s),"product_id"]) for s in ("train","validation","test")}
    assert not (sets["train"]&sets["validation"] or sets["train"]&sets["test"] or sets["validation"]&sets["test"])

def test_preprocessor_fit_is_train_only_and_schema_stable():
    data=load_data(ROOT/"ml_workspace/data/products_taxonomy_v2.csv")
    # Small deterministic subset retaining every split; validates lifecycle without full training.
    sample=pd.concat([p.head(30) for _,p in data.frame.groupby("split")],ignore_index=True)
    data.frame=sample
    features=prepare_features(data,TrainingConfig(max_features=200))
    train=set(sample.loc[sample.split.eq("train") & sample.domain_label.ne("unknown_needs_review"),"product_id"]); other=set(sample.loc[~sample.split.eq("train"),"product_id"])
    assert set(features.fit_product_ids)==train and not (set(features.fit_product_ids)&other)
    assert features.feature_schema==FEATURE_COLUMNS
    for task in ("domain","activities","product_category","work_types","room_types"):
        for split in ("train","validation","test"):
            rows=sample[sample.split.eq(split)].reset_index(drop=True)
            mask=features.supervision_mask_by_task[task][split]
            assert not mask[rows.domain_label.eq("unknown_needs_review").to_numpy()].any()

def test_filtering_unknown_does_not_change_split_or_groups():
    manifest=pd.read_csv(ROOT/"ml_workspace/data/splits/split_manifest.csv")
    data=pd.read_csv(ROOT/"ml_workspace/data/products_taxonomy_v2.csv",usecols=["product_id","domain_label","split","duplicate_group"])
    known=data[data.domain_label.ne("unknown_needs_review")]
    assert known.merge(manifest[["product_id","split"]],on="product_id",suffixes=("_data","_manifest")).eval("split_data == split_manifest").all()
    assert known.groupby("duplicate_group").split.nunique().max()==1
