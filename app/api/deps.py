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
def get_catalog_matching_classifier() -> Any:
    """Independent full-catalog matcher; intentionally not used by bindings or ranking."""
    settings = get_settings()
    if settings.catalog_matching_classifier_backend != "catalog_tfidf":
        raise ValueError(f"Unsupported catalog matching backend: {settings.catalog_matching_classifier_backend}")
    classifier = load("app.ml.catalog_matching:CatalogMatchingClassifier")
    return classifier(settings.catalog_matching_artifact_path)


@lru_cache
def get_estimate_engine() -> Any:
    return load(get_settings().engine_impl)(ranker=get_ranker())


@lru_cache
def get_gigachat() -> Any:
    from app.llm.gigachat import GigaChatClient
    return GigaChatClient(get_settings())


def get_repo(session: Session = Depends(get_session)) -> CatalogRepo:
    return CatalogRepo(session)
