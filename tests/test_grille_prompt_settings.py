import pytest

from src.app.models import GrillePromptSettings


def test_get_current_creates_defaults(app):
    """Ensure default config is created with non-null fields."""
    with app.app_context():
        assert GrillePromptSettings.query.count() == 0

        settings = GrillePromptSettings.get_current()

        assert settings.prompt_template
        for level in range(1, 7):
            assert getattr(settings, f"level{level}_description")

        assert GrillePromptSettings.query.count() == 1


def test_get_current_returns_existing(app):
    """Second call should not create another entry."""
    with app.app_context():
        first = GrillePromptSettings.get_current()
        count_before = GrillePromptSettings.query.count()

        second = GrillePromptSettings.get_current()

        assert GrillePromptSettings.query.count() == count_before == 1
        assert second.id == first.id
