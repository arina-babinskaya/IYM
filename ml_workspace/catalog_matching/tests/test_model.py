import pytest
pytest.importorskip("sklearn")
from ml_workspace.catalog_matching.models.tfidf_logreg import CatalogClassifier, TrainingConfig, evaluate
from ml_workspace.catalog_matching.inference.predictor import CatalogPredictor

def train_small():
    texts=["семена томата","семена огурца","семена цветов","краска белая","краска для стен","эмаль красная"]*2
    labels=(["garden.seeds"]*3+["finishing.paint"]*3)*2
    model=CatalogClassifier(TrainingConfig(min_df=1,word_max_features=100,char_max_features=200,max_iter=100,C=1.0))
    return model.fit(texts,labels),texts,labels

def test_small_training_and_metrics():
    model,texts,labels=train_small(); metrics=evaluate(model.pipeline,texts,labels)
    assert 0 <= metrics["accuracy"] <= 1 and "macro_f1" in metrics

def test_save_load_top1_topk_and_name_only(tmp_path):
    model,_,_=train_small(); artifact=tmp_path/"artifact"; model.save(artifact,dataset_fingerprint="fixture",review_threshold=.99)
    predictor=CatalogPredictor(artifact); out=predictor.predict_category("семена моркови",top_k=2)
    assert out.category_id in {"garden.seeds","finishing.paint"}
    assert len(out.alternatives)==1 and out.model=="catalog-tfidf-logreg-v1"
    assert predictor.predict_category("семена моркови").category_id == out.category_id

def test_empty_name_rejected(tmp_path):
    model,_,_=train_small(); model.save(tmp_path/"a"); p=CatalogPredictor(tmp_path/"a")
    with pytest.raises(ValueError): p.predict_category("")

def test_unknown_product_returns_one_reviewable_prediction(tmp_path):
    model,_,_=train_small(); model.save(tmp_path/"a",review_threshold=.999)
    out=CatalogPredictor(tmp_path/"a").predict_category("квантовый неопознанный прибор")
    assert isinstance(out.category_id,str) and out.needs_review
