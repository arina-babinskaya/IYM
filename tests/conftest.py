import os
from pathlib import Path

import pytest

os.environ["RC_DATABASE_URL"] = os.environ.get("RC_TEST_DATABASE_URL", "sqlite:///./.pytest.sqlite")
os.environ["RC_OLLAMA_URL"] = "http://127.0.0.1:9"
os.environ["RC_LLM_RETRIES"] = "0"
os.environ["RC_ML_CLASSIFIER_BACKEND"] = "baseline"

from app.catalog.loader import load_catalog
from app.db import Base, get_engine, get_sessionmaker, init_db

SAMPLE = Path(__file__).resolve().parent.parent / "mock_catalog" / "sample_catalog.xml"
SAMPLE_JSON = SAMPLE.with_suffix(".json")


@pytest.fixture(scope="session")
def db():
    Base.metadata.drop_all(get_engine())
    init_db()
    yield
    get_engine().dispose()
    if os.path.exists(".pytest.sqlite"):
        os.remove(".pytest.sqlite")


@pytest.fixture(scope="session")
def ingested(db):
    with get_sessionmaker()() as s:
        return load_catalog(s, SAMPLE)
