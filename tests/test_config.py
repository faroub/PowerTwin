"""Test application settings and configuration loading."""

from backend.app.core.config import Settings


def test_settings_defaults() -> None:
    """Test configuration settings default values."""
    settings = Settings()
    assert settings.PROJECT_NAME == "PowerTwin BESS Simulator"
    assert settings.PORT == 8000
    assert "postgresql+asyncpg://" in settings.DATABASE_URL
    assert settings.API_V1_STR == "/api/v1"
