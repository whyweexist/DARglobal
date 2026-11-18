import pytest
from app.core.config import settings
from app.db.session import engine


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/test.db')
    monkeypatch.setenv('OPENROUTER_API_KEY', '')
    monkeypatch.setenv('RAG_LIVE_SEARCH', 'false')
    monkeypatch.setenv('WASALT_AUTHORIZED', 'false')
    settings.cache_clear()
    engine.cache_clear()
    from app.agents.tools import _access_cooldowns
    _access_cooldowns.clear()
    yield
    _access_cooldowns.clear()
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()
