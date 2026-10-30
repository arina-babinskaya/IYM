from __future__ import annotations

import hashlib, json, platform, time
from dataclasses import asdict, dataclass
from pathlib import Path
import joblib, numpy as np, sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, precision_recall_fscore_support, top_k_accuracy_score
from ..taxonomy.catalog_taxonomy import snapshot, TAXONOMY_VERSION

@dataclass(frozen=True)
class TrainingConfig:
    model_name: str = "catalog-tfidf-logreg-v1"
    feature_mode: str = "name"
    word_ngram_range: tuple[int,int] = (1,2)
    char_ngram_range: tuple[int,int] = (3,5)
    word_max_features: int = 150_000
    char_max_features: int = 200_000
    min_df: int = 2
    C: float = 4.0
    class_weight: str | None = "balanced"
    max_iter: int = 500
    random_state: int = 20261029

def make_pipeline(config: TrainingConfig) -> Pipeline:
    features=FeatureUnion([
        ("word",TfidfVectorizer(lowercase=True,ngram_range=config.word_ngram_range,min_df=config.min_df,max_features=config.word_max_features,sublinear_tf=True)),
        ("char",TfidfVectorizer(lowercase=True,analyzer="char_wb",ngram_range=config.char_ngram_range,min_df=config.min_df,max_features=config.char_max_features,sublinear_tf=True)),
    ])
    estimator=LogisticRegression(C=config.C,class_weight=config.class_weight,max_iter=config.max_iter,random_state=config.random_state,solver="lbfgs")
    return Pipeline([("tfidf",features),("classifier",estimator)])

def evaluate(model: Pipeline, texts: list[str], labels: list[str]) -> dict:
    pred=model.predict(texts); prob=model.predict_proba(texts); classes=model.classes_
    p,r,f,_=precision_recall_fscore_support(labels,pred,average="macro",zero_division=0)
    _,_,wf,_=precision_recall_fscore_support(labels,pred,average="weighted",zero_division=0)
    metrics={"accuracy":accuracy_score(labels,pred),"macro_precision":p,"macro_recall":r,"macro_f1":f,"weighted_f1":wf,
             "per_class":classification_report(labels,pred,output_dict=True,zero_division=0)}
    for k in (3,5):
        if len(classes)>=k: metrics[f"top_{k}_accuracy"]=top_k_accuracy_score(labels,prob,k=k,labels=classes)
    return metrics

class CatalogClassifier:
    def __init__(self, config: TrainingConfig | None=None): self.config=config or TrainingConfig(); self.pipeline=make_pipeline(self.config); self.metrics={}; self.training_seconds=None
    def fit(self,texts:list[str],labels:list[str]):
        start=time.perf_counter(); self.pipeline.fit(texts,labels); self.training_seconds=time.perf_counter()-start; return self
    def save(self,path:str|Path,dataset_fingerprint:str="",metrics:dict|None=None,review_threshold:float|None=None):
        path=Path(path); path.mkdir(parents=True,exist_ok=False)
        joblib.dump(self.pipeline,path/"model.joblib")
        classes=list(self.pipeline.classes_); meta={"model_name":self.config.model_name,"taxonomy_version":TAXONOMY_VERSION,"input_schema":{"required":["product_name"],"optional":["description"],"feature_mode":self.config.feature_mode},"classes":classes,"class_to_index":{x:i for i,x in enumerate(classes)},"training_config":asdict(self.config),"dependency_versions":{"python":platform.python_version(),"scikit_learn":sklearn.__version__,"numpy":np.__version__,"joblib":joblib.__version__},"dataset_fingerprint":dataset_fingerprint,"metrics":metrics or self.metrics,"review_threshold":review_threshold,"training_seconds":self.training_seconds,"probability_note":"Uncalibrated LogisticRegression predict_proba; validate reliability before interpreting as calibrated confidence."}
        (path/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8"); (path/"taxonomy.json").write_text(json.dumps(snapshot(),ensure_ascii=False,indent=2),encoding="utf-8")
        checks={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir() if p.is_file()}; (path/"checksums.json").write_text(json.dumps(checks,indent=2),encoding="utf-8")
        return path
