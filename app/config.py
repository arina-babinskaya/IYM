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
    # ``tfidf`` remains accepted as a backwards-compatible alias for ``trained``.
    ml_classifier_backend: Literal["baseline", "trained", "tfidf"] = "trained"
    ml_classifier_artifact_path: Path = Path("ml_workspace/model/tfidf_logreg")
    # Independent full-assortment classifier. This configuration is never read by ranking.
    catalog_matching_classifier_backend: Literal["catalog_tfidf"] = "catalog_tfidf"
    catalog_matching_artifact_path: Path = Path("ml_workspace/catalog_matching/model_v2")
    ranker_impl: str = "app.ml.ranker:ContextRanker"
    autobind_min_confidence: float = 0.7

    gigachat_enabled: bool = False
    gigachat_credentials: str | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_api_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_model: str = "GigaChat-2"
    gigachat_timeout_s: float = 45.0
    gigachat_retries: int = 3
    gigachat_verify_ssl: bool = True
    # Optional PEM bundle shared by OAuth, discovery, chat, retries and explanations.
    gigachat_ca_bundle: Path | None = None
    gigachat_structured_output: bool = True
    gigachat_repair_invalid_response: bool = True
    gigachat_cache_path: Path = Path(".cache/gigachat.sqlite")
    gigachat_token_budget: int | None = None
    gigachat_token_reservation: int = 2500
    gigachat_max_requests: int | None = None
    gigachat_autobind_max_products: int = 30
    gigachat_cache_namespace: str = "hybrid-v2"
    gigachat_binding_confidence: float = 0.8
    gigachat_accept_material_only: bool = True
    gigachat_explanations: bool = False
    gigachat_explanation_max_items: int = 30

    consultant_session_secret: str = "repaircalc-local-consultant-secret-change-in-production"
    consultant_cookie_secure: bool = False
    consultant_context_messages: int = 20
    consultant_context_chars: int = 24000
    consultant_max_message_chars: int = 6000
    consultant_max_output_tokens: int = 1200

    # Поиск декора и мебели по фото: модель GigaChat, которая понимает изображения
    decor_photo_model: str = "GigaChat-2-Max"
    decor_photo_max_mb: int = 10

    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
