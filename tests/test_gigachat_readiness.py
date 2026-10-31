from pathlib import Path

from app.config import Settings
from scripts.gigachat_readiness import readiness


def configured(tmp_path: Path, **overrides) -> Settings:
    bundle = tmp_path / "ca.pem"
    # Use the certifi bundle installed with httpx: it is valid and contains no project secret.
    import certifi
    options = dict(gigachat_enabled=True, gigachat_credentials="configured-not-returned",
                   gigachat_ca_bundle=Path(certifi.where()))
    options.update(overrides)
    return Settings(**options)


def test_readiness_accepts_valid_configuration_without_exposing_secret(tmp_path):
    report = readiness(configured(tmp_path))
    assert report["ready"] is True
    assert report["credentials_configured"] is True
    assert "configured-not-returned" not in str(report)


def test_readiness_reports_disabled_missing_credentials_and_bundle(tmp_path):
    report = readiness(Settings(gigachat_enabled=False, gigachat_credentials=None,
                                gigachat_ca_bundle=tmp_path / "missing.pem"))
    assert report["ready"] is False
    assert report["enabled"] is False and report["credentials_configured"] is False
    assert report["ca_bundle_exists"] is False and len(report["errors"]) == 3


def test_readiness_rejects_disabled_ssl_verification(tmp_path):
    report = readiness(configured(tmp_path, gigachat_verify_ssl=False))
    assert report["ready"] is False
    assert any("SSL verification" in error for error in report["errors"])
