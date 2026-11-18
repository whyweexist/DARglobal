import pytest
from app.core.config import settings
from app.ingestion.policy import PolicyDenied, validate_official_url, assert_source_authorized
from app.llm.registry import ModelRegistry


def test_wasalt_never_crawls_without_authorization():
    with pytest.raises(PolicyDenied):
        validate_official_url('https://wasalt.sa/en/property/example', 'wasalt')


def test_wasalt_requires_auth_reference(monkeypatch):
    monkeypatch.setenv('WASALT_AUTHORIZED', 'true')
    settings.cache_clear()
    with pytest.raises(PolicyDenied):
        assert_source_authorized('wasalt')


def test_rejects_arbitrary_host_without_dns():
    with pytest.raises(PolicyDenied):
        validate_official_url('https://evil.example/redirect', 'darglobal')
    with pytest.raises(PolicyDenied):
        validate_official_url('http://darglobal.co.uk/', 'darglobal')


def test_model_catalog_prices_must_be_zero():
    assert ModelRegistry._free({'prompt':'0','completion':'0','request':'0'})
    assert not ModelRegistry._free({'prompt':'0.01','completion':'0','request':'0'})
    assert not ModelRegistry._free({})
