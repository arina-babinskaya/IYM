from __future__ import annotations

import hashlib, json
from dataclasses import dataclass, asdict
from pathlib import Path
import joblib, numpy as np

@dataclass(frozen=True)
class Alternative:
    category_id: str; category_name: str; confidence: float
@dataclass(frozen=True)
class CategoryPrediction:
    category_id: str; category_name: str; confidence: float; alternatives: tuple[Alternative,...]; model: str; needs_review: bool; score_type: str="uncalibrated_probability"
    def to_dict(self):
        d=asdict(self); d["alternatives"]=list(d["alternatives"]); return d

class CatalogPredictor:
    def __init__(self,artifact_dir:str|Path):
        p=Path(artifact_dir); checks=json.loads((p/"checksums.json").read_text());
        for name,expected in checks.items():
            if hashlib.sha256((p/name).read_bytes()).hexdigest()!=expected: raise ValueError(f"artifact checksum mismatch: {name}")
        self.model=joblib.load(p/"model.joblib"); self.metadata=json.loads((p/"metadata.json").read_text()); taxonomy=json.loads((p/"taxonomy.json").read_text()); self.names={x["id"]:x["name"] for x in taxonomy["categories"]}
    def predict_category(self,product_name:str,description:str|None=None,top_k:int=3)->CategoryPrediction:
        if not isinstance(product_name,str) or not product_name.strip(): raise ValueError("product_name must be non-empty")
        mode=self.metadata["input_schema"]["feature_mode"]; text=product_name.strip()
        if mode=="name_description" and description: text += " " + description.strip()
        probs=self.model.predict_proba([text])[0]; order=np.argsort(probs)[::-1]; best=int(order[0]); cid=str(self.model.classes_[best]); threshold=self.metadata.get("review_threshold")
        alternatives=tuple(Alternative(str(self.model.classes_[i]),self.names.get(str(self.model.classes_[i]),str(self.model.classes_[i])),float(probs[i])) for i in order[1:max(1,top_k)])
        return CategoryPrediction(cid,self.names.get(cid,cid),float(probs[best]),alternatives,self.metadata["model_name"],bool(threshold is not None and probs[best]<threshold))

def predict_category(artifact_dir:str|Path,product_name:str,description:str|None=None)->CategoryPrediction:
    return CatalogPredictor(artifact_dir).predict_category(product_name,description)
