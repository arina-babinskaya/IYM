from functools import lru_cache
from importlib import import_module
from typing import Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.catalog.repository import CatalogRepo
from app.config import get_settings
from app.db import get_session


def load(path: str) -> Any:
    module, _, name = path.partition(":")
    return getattr(import_module(module), name)


@lru_cache
def get_ranker() -> Any:
    return load(get_settings().ranker_impl)()


@lru_cache
def get_classifier() -> Any:
    settings = get_settings()
    if settings.ml_classifier_backend in {"trained", "tfidf"}:
        classifier = load("app.ml.tfidf:TfidfClassifier")
        return classifier(settings.ml_classifier_artifact_path)
    return load(settings.classifier_impl)()


@lru_cache
def get_estimate_engine() -> Any:
    return load(get_settings().engine_impl)(ranker=get_ranker())


def get_repo(session: Session = Depends(get_session)) -> CatalogRepo:
    return CatalogRepo(session)
