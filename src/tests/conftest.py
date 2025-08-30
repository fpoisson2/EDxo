import os
import pytest

@pytest.fixture(autouse=True)
def _set_env_defaults():
    os.environ.setdefault('SECRET_KEY', 'test')
    os.environ.setdefault('RECAPTCHA_PUBLIC_KEY', 'test')
    os.environ.setdefault('RECAPTCHA_PRIVATE_KEY', 'test')
