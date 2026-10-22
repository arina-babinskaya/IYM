from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RC_", extra="ignore")

    database_url: str = "sqlite:///./repaircalc_local.sqlite"
    auto_create_tables: bool = True

    catalog_yml_url: str = "https://fidsout.maxidom.ru/fids/export_yandex_spb.xml"
    catalog_path: str = "data/catalog.json"
    catalog_timeout_s: float = 600.0

    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:14b-instruct-q4_K_M"
    embed_model: str = "bge-m3"
    llm_num_ctx: int = 8192
    llm_keep_alive: str = "24h"
    llm_timeout_s: float = 120.0
    llm_retries: int = 2
    llm_cache_size: int = 4096

    qdrant_url: str = "http://localhost:6333"

    engine_impl: str = "app.engine.baseline:BaselineEngine"
    classifier_impl: str = "app.ml.baseline:KeywordClassifier"
    ml_classifier_backend: Literal["baseline", "tfidf"] = "baseline"
    ml_classifier_artifact_path: Path = Path("ml_workspace/artifacts/models/tfidf_logreg_v2")
    ranker_impl: str = "app.ml.baseline:RatingRanker"
    autobind_min_confidence: float = 0.8

    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
