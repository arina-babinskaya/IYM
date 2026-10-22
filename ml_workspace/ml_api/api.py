"""Unified leakage-safe multi-task API (domain, category, work types)."""
from __future__ import annotations
import importlib.metadata, json, platform, time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence
import joblib, numpy as np, pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, f1_score
from sklearn.multiclass import OneVsRestClassifier
from .feature_schema import FEATURE_COLUMNS, STRUCTURED_FEATURE_COLUMNS, build_input_text, select_source_features, validate_feature_schema
from .metrics import compute_metrics
from .types import *
from ml_workspace.taxonomy.taxonomy_v2 import (ACTIVITIES,PRODUCT_CATEGORIES,ROOM_TYPES,
    TAXONOMY_VERSION,WORK_IDS,stages_for_work_types)

DOMAIN_CLASSES=["renovation","furnishing","non_renovation"]
MULTILABEL_TASKS={"activities","work_types","room_types"}

def load_data(data_path: Path, weak_labels_path: Path|None=None, reviewed_paths: Sequence[Path]=(),
              split_manifest_path: Path|None=None, taxonomy_path: Path|None=None,
              taxonomy_version: str=TAXONOMY_VERSION, label_policy: str="automatic_weak_labels",
              random_seed: int=20261022)->DatasetBundle:
    if weak_labels_path is not None: raise ValueError("taxonomy_v1 does not use retired manual-review inputs")
    f=pd.read_csv(data_path,keep_default_na=False,low_memory=False)
    required=set(FEATURE_COLUMNS+["product_id","domain_label","activities","product_category","work_types","renovation_stages","room_types","split","taxonomy_version"])
    if missing:=sorted(required-set(f)): raise ValueError(f"Missing prepared columns: {missing}")
    if set(f.taxonomy_version)!={taxonomy_version}: raise ValueError("Taxonomy version mismatch")
    select_source_features(f); f["labels"]=f.work_types.map(json.loads)
    for column in ("activities","room_types"): f[column]=f[column].map(json.loads)
    f["text"]=[build_input_text(r) for r in f.to_dict("records")]
    if "input_text" in f and not (f.input_text==f.text).all(): raise ValueError("input_text violates approved feature builder")
    classes={"domain":DOMAIN_CLASSES,"activities":[x["id"] for x in ACTIVITIES],"product_category":PRODUCT_CATEGORIES,"work_types":WORK_IDS,"room_types":ROOM_TYPES}
    return DatasetBundle(f,WORK_IDS,taxonomy_version,label_policy,split_manifest_path or data_path.parent/"split_manifest.csv",classes)

def _structured(f: pd.DataFrame)->pd.DataFrame:
    validate_feature_schema(STRUCTURED_FEATURE_COLUMNS); out=f[STRUCTURED_FEATURE_COLUMNS].copy()
    for c in ["price","characteristic_count","information_completeness"]: out[c]=pd.to_numeric(out[c],errors="coerce").fillna(0)
    for c in ["source_category","sale_unit","brand_name"]: out[c]=out[c].astype(str).fillna("<missing>")
    return out

def _load_encoder(name: str,device: str):
    try: from sentence_transformers import SentenceTransformer
    except ImportError as e: raise RuntimeError("sentence-transformers unavailable; use tfidf_logreg") from e
    return SentenceTransformer(name,device=device)

def prepare_features(data: DatasetBundle,config: TrainingConfig,cache_dir: Path|None=None,encoder: Any=None)->FeatureBundle:
    f=data.frame; masks={s:f.split.eq(s).to_numpy() for s in ("train","validation","test")}
    if any(not m.any() for m in masks.values()): raise ValueError("All three splits must be non-empty")
    if config.experiment=="tfidf_logreg":
        prep=TfidfVectorizer(ngram_range=(1,2),min_df=1,max_features=config.max_features,sublinear_tf=True)
        prep.fit(f.loc[masks["train"],"text"]); x={s:prep.transform(f.loc[m,"text"]) for s,m in masks.items()}; schema=FEATURE_COLUMNS
    elif config.experiment=="embeddings_logreg":
        encoder=encoder or _load_encoder(config.embedding_model,"cuda" if config.use_gpu else "cpu")
        matrix=np.asarray(encoder.encode(f.text.tolist(),batch_size=64,show_progress_bar=True,normalize_embeddings=True))
        x={s:matrix[m] for s,m in masks.items()}; prep={"embedding_model":config.embedding_model}; schema=FEATURE_COLUMNS
    elif config.experiment=="catboost_structured":
        raw=_structured(f); x={s:raw.loc[m].reset_index(drop=True) for s,m in masks.items()}; prep={"schema":STRUCTURED_FEATURE_COLUMNS}; schema=STRUCTURED_FEATURE_COLUMNS
    else: raise ValueError(config.experiment)
    domain=np.array([data.task_classes["domain"].index(v) if v in data.task_classes["domain"] else -1 for v in f.domain_label])
    category=np.array([data.task_classes["product_category"].index(v) if v in data.task_classes["product_category"] else -1 for v in f.product_category])
    encoded={}
    for task,column in (("activities","activities"),("work_types","labels"),("room_types","room_types")):
        idx={c:i for i,c in enumerate(data.task_classes[task])}; matrix=np.zeros((len(f),len(idx)),dtype=np.int8)
        for r,labels in enumerate(f[column]):
            for label in labels: matrix[r,idx[label]]=1
        encoded[task]=matrix
    arrays={"domain":domain,"product_category":category,**encoded}
    tasks={t:{s:y[m] for s,m in masks.items()} for t,y in arrays.items()}
    validity={"domain":"domain_valid","activities":"activity_valid","product_category":"product_category_valid","work_types":"work_types_valid","room_types":"room_types_valid"}
    eligible={task:f[column].astype(bool).to_numpy() for task,column in validity.items()}
    supervision={t:{s:mask[m] for s,m in masks.items()} for t,mask in eligible.items()}
    fitted=f.loc[masks["train"] & eligible["domain"],"product_id"].astype(int).tolist()
    return FeatureBundle(config.experiment,data,x,tasks["work_types"],{s:f.loc[m,"product_id"].astype(int).to_numpy() for s,m in masks.items()},prep,schema,encoder,tasks,fitted,supervision)

def train(features: FeatureBundle,config: TrainingConfig)->ModelBundle:
    x=features.x_by_split["train"]; models={}
    if features.experiment!=config.experiment: raise ValueError("Feature/experiment mismatch")
    if config.experiment=="catboost_structured":
        try: from catboost import CatBoostClassifier
        except ImportError as e: raise RuntimeError("Install catboost") from e
        for task,sets in features.y_by_task.items():
            y=sets["train"]; mask=features.supervision_mask_by_task[task]["train"]
            model=CatBoostClassifier(iterations=config.catboost_iterations,depth=config.catboost_depth,learning_rate=config.catboost_learning_rate,loss_function="MultiClass" if y.ndim==1 else "MultiLogloss",verbose=False,random_seed=config.random_seed,task_type="GPU" if config.use_gpu else "CPU",allow_writing_files=False)
            model.fit(x.loc[mask].reset_index(drop=True),y[mask],cat_features=["source_category","sale_unit","brand_name"]); models[task]=model
    else:
        for task,sets in features.y_by_task.items():
            y=sets["train"]; mask=features.supervision_mask_by_task[task]["train"]
            model=(OneVsRestClassifier(LogisticRegression(max_iter=config.logistic_max_iter,class_weight="balanced",solver="liblinear"),n_jobs=1) if task in MULTILABEL_TASKS else LogisticRegression(max_iter=config.logistic_max_iter,class_weight="balanced",solver="lbfgs"))
            model.fit(x[mask],y[mask]); models[task]=model
    thresholds={c:.5 for task in MULTILABEL_TASKS for c in features.dataset.task_classes[task]}
    metadata={"trained_at_unix":time.time(),"fit_product_ids":features.fit_product_ids,"evaluation_warning":"Agreement with weak labels only; not independently verified accuracy."}
    return ModelBundle(config.experiment,models,features.preprocessor,features.dataset.class_names,thresholds,features.dataset.taxonomy_version,features.feature_schema,config,features.encoder,metadata,features.dataset.task_classes)

def _scores(model: ModelBundle,x: Any)->dict[str,np.ndarray]:
    result={}
    for task,estimator in model.estimator.items():
        raw=np.asarray(estimator.predict_proba(x))
        if task not in MULTILABEL_TASKS and raw.shape[1]!=len(model.task_classes[task]):
            padded=np.zeros((len(raw),len(model.task_classes[task])),dtype=float)
            for source_index,class_index in enumerate(estimator.classes_): padded[:,int(class_index)]=raw[:,source_index]
            raw=padded
        result[task]=raw
    return result

def _single_metrics(y: np.ndarray,s: np.ndarray,classes: list[str],mask: np.ndarray)->dict[str,Any]:
    pred=s[mask].argmax(1); p,r,f,sup=precision_recall_fscore_support(y[mask],pred,labels=range(len(classes)),zero_division=0)
    return {"macro_precision":float(p.mean()),"macro_recall":float(r.mean()),"macro_f1":float(f.mean()),"weighted_f1":float(np.average(f,weights=sup)) if sup.sum() else 0.0,"per_class":{c:{"precision":float(p[i]),"recall":float(r[i]),"f1":float(f[i]),"support":int(sup[i])} for i,c in enumerate(classes)}}

def validate(model: ModelBundle,features: FeatureBundle)->ValidationResult:
    scores=_scores(model,features.x_by_split["validation"]); metrics={}
    for task in MULTILABEL_TASKS:
        mask=features.supervision_mask_by_task[task]["validation"]; y=features.y_by_task[task]["validation"][mask]; task_scores=scores[task][mask]
        for i,c in enumerate(model.task_classes[task]):
            model.thresholds[c]=float(max(np.arange(.2,.81,.05),key=lambda t:f1_score(y[:,i],task_scores[:,i]>=t,zero_division=0))) if y[:,i].any() else .5
        pred=task_scores>=np.array([model.thresholds[c] for c in model.task_classes[task]])
        metrics[task]=compute_metrics(y,pred,task_scores,model.task_classes[task]); metrics[task]["excluded_invalid_rows"]=int((~mask).sum())
    for task in ("domain","product_category"):
        metrics[task]=_single_metrics(features.y_by_task[task]["validation"],scores[task],model.task_classes[task],features.supervision_mask_by_task[task]["validation"])
    metrics["limitation"]="Technical agreement with automatic labels, not real-world accuracy."
    y=features.y_by_task["work_types"]["validation"]; mask=features.supervision_mask_by_task["work_types"]["validation"]
    return ValidationResult(model.thresholds,metrics,{c:int(y[mask,i].sum()) for i,c in enumerate(model.task_classes["work_types"])})

def evaluate(model: ModelBundle,features: FeatureBundle,split: str="test")->EvaluationResult:
    if split not in ("validation","test"): raise ValueError("Only validation/test evaluation is allowed")
    scores=_scores(model,features.x_by_split[split]); metrics={}
    for task in MULTILABEL_TASKS:
        mask=features.supervision_mask_by_task[task][split]; y=features.y_by_task[task][split][mask]; task_scores=scores[task][mask]; pred=task_scores>=np.array([model.thresholds[c] for c in model.task_classes[task]])
        metrics[task]=compute_metrics(y,pred,task_scores,model.task_classes[task]); metrics[task]["excluded_invalid_rows"]=int((~mask).sum())
    for task in ("domain","product_category"):
        metrics[task]=_single_metrics(features.y_by_task[task][split],scores[task],model.task_classes[task],features.supervision_mask_by_task[task][split])
    metrics["limitation"]="Weak-label test measures rule agreement only."
    work_mask=features.supervision_mask_by_task["work_types"][split]; y=features.y_by_task["work_types"][split][work_mask]; work_scores=scores["work_types"][work_mask]; pred=work_scores>=np.array([model.thresholds[c] for c in model.task_classes["work_types"]])
    return EvaluationResult(split,metrics,features.ids_by_split[split][work_mask].tolist(),y,pred.astype(int),work_scores,"weak_labels_provisional_task_masks_applied")

def save_model(model: ModelBundle,artifact_dir: Path,validation: ValidationResult|None=None,evaluation: EvaluationResult|None=None)->None:
    artifact_dir.mkdir(parents=True,exist_ok=True)
    if any(artifact_dir.iterdir()): raise FileExistsError(f"Artifact directory not empty: {artifact_dir}")
    meta={"format_version":2,"experiment":model.experiment,"taxonomy_version":model.taxonomy_version,"class_names":model.class_names,"task_classes":model.task_classes,"feature_schema":model.feature_schema,"training_config":asdict(model.training_config),"metadata":model.metadata}
    versions={"python":platform.python_version()}
    for p in ("numpy","pandas","scikit-learn","joblib"):
        try: versions[p]=importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError: versions[p]="not-installed"
    for name,value in (("metadata.json",meta),("thresholds.json",model.thresholds),("validation_metrics.json",validation.metrics if validation else {}),("evaluation_metrics.json",evaluation.metrics if evaluation else {}),("dependency_versions.json",versions)):
        (artifact_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    joblib.dump(model.estimator,artifact_dir/"estimators.joblib"); joblib.dump(model.preprocessor,artifact_dir/"preprocessor.joblib")
    if model.experiment=="embeddings_logreg" and model.encoder is not None and hasattr(model.encoder,"save"):
        model.encoder.save(str(artifact_dir/"sentence_encoder"))

def load_model(artifact_dir: Path,expected_taxonomy_version: str=TAXONOMY_VERSION,trusted: bool=False,encoder: Any=None)->ModelBundle:
    if not trusted: raise PermissionError("trusted=True required for local serialized artifacts")
    artifact_dir=Path(artifact_dir)
    required={"metadata.json","thresholds.json","dependency_versions.json","estimators.joblib","preprocessor.joblib"}
    if missing:=sorted(name for name in required if not (artifact_dir/name).is_file()):
        raise FileNotFoundError(f"Incomplete model artifact at {artifact_dir}; missing: {missing}")
    meta=json.loads((artifact_dir/"metadata.json").read_text(encoding="utf-8"))
    if meta.get("format_version")!=2: raise ValueError(f"Unsupported artifact format: {meta.get('format_version')!r}")
    if meta["taxonomy_version"]!=expected_taxonomy_version: raise ValueError("Taxonomy mismatch")
    expected_tasks={"domain","activities","product_category","work_types","room_types"}
    if missing_tasks:=sorted(expected_tasks-set(meta.get("task_classes",{}))): raise ValueError(f"Artifact task mappings missing: {missing_tasks}")
    if set(meta["task_classes"]["work_types"])!=set(WORK_IDS): raise ValueError("Artifact work types do not match taxonomy_v2")
    validate_feature_schema(meta["feature_schema"]); raw=meta["training_config"]; raw["tasks"]=tuple(raw.get("tasks",[])); cfg=TrainingConfig(**raw)
    if meta["experiment"]=="embeddings_logreg" and encoder is None:
        local=artifact_dir/"sentence_encoder"; encoder=_load_encoder(str(local) if local.exists() else cfg.embedding_model,"cuda" if cfg.use_gpu else "cpu")
    thresholds=json.loads((artifact_dir/"thresholds.json").read_text(encoding="utf-8"))
    multilabel_classes={label for task in MULTILABEL_TASKS for label in meta["task_classes"][task]}
    if missing_thresholds:=sorted(multilabel_classes-set(thresholds)): raise ValueError(f"Artifact thresholds missing: {missing_thresholds}")
    estimators=joblib.load(artifact_dir/"estimators.joblib")
    if missing_estimators:=sorted(expected_tasks-set(estimators)): raise ValueError(f"Artifact estimators missing: {missing_estimators}")
    return ModelBundle(meta["experiment"],estimators,joblib.load(artifact_dir/"preprocessor.joblib"),meta["class_names"],thresholds,meta["taxonomy_version"],meta["feature_schema"],cfg,encoder,meta.get("metadata",{}),meta["task_classes"])

def _frame(products: Sequence[ProductInput])->pd.DataFrame:
    rows=[]
    for p in products:
        if not p.name.strip(): raise ValueError("Product name is required")
        rows.append({"product_id":p.product_id,"name":p.name,"source_category":p.source_category,"category_names":p.category_names,"description_clean":p.description,"marketing_description_clean":p.marketing_description,"important_attributes_json":json.dumps(p.characteristics,ensure_ascii=False),"characteristics_json":json.dumps(p.characteristics,ensure_ascii=False),"brand_name":p.brand_name,"sale_unit":p.sale_unit,"price":p.price or 0,"characteristic_count":len(p.characteristics),"information_completeness":sum(bool(x) for x in (p.name,p.source_category,p.description,p.characteristics))/4})
    f=pd.DataFrame(rows); f["text"]=[build_input_text(r) for r in f.to_dict("records")]; return f

def predict(model: ModelBundle,products: ProductBatch)->Prediction|list[Prediction]:
    single=isinstance(products,ProductInput); batch=[products] if single else list(products)
    if not batch:return []
    f=_frame(batch); x=model.preprocessor.transform(f.text) if model.experiment=="tfidf_logreg" else (_structured(f) if model.experiment=="catboost_structured" else np.asarray((model.encoder or _load_encoder(model.training_config.embedding_model,"cpu")).encode(f.text.tolist(),normalize_embeddings=True)))
    scores=_scores(model,x); out=[]
    for i,p in enumerate(batch):
        dims={t:{c:float(scores[t][i,j]) for j,c in enumerate(model.task_classes[t])} for t in scores}; domain=max(dims["domain"],key=dims["domain"].get); confidence=dims["domain"][domain]
        category=max(dims["product_category"],key=dims["product_category"].get) if domain in {"renovation","furnishing"} else ""; works=[c for c,v in dims["work_types"].items() if v>=model.thresholds[c]] if domain=="renovation" else []
        activities=[c for c,v in dims["activities"].items() if v>=model.thresholds[c]] if domain!="non_renovation" else []
        rooms=[c for c,v in dims["room_types"].items() if v>=model.thresholds[c]] if domain=="furnishing" else []
        status="non_renovation" if domain=="non_renovation" else "unknown" if domain=="unknown_needs_review" else "predicted"
        if confidence<.55: status="uncertain"; domain="unknown_needs_review"; category=""; works=[]; activities=[]; rooms=[]
        out.append(Prediction(product_id=p.product_id,labels=works,scores=dims["work_types"],status=status,domain_label=domain,product_category=category,work_types=works,renovation_stages=stages_for_work_types(works),activities=activities,room_types=rooms,dimension_scores=dims))
    return out[0] if single else out
