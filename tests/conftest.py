import pytest

from app.core.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path)
