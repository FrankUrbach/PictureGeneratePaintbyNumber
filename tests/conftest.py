from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import importlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw


@pytest.fixture
def image_factory():
    def _create(
        path: Path,
        *,
        size: tuple[int, int] = (64, 64),
        left_color: tuple[int, int, int] = (255, 0, 0),
        right_color: tuple[int, int, int] = (0, 0, 255),
    ) -> Path:
        img = Image.new("RGB", size, left_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([size[0] // 2, 0, size[0] - 1, size[1] - 1], fill=right_color)
        img.save(path)
        return path

    return _create


@pytest.fixture
def image_bytes_factory():
    def _create(
        *,
        size: tuple[int, int] = (64, 64),
        left_color: tuple[int, int, int] = (255, 0, 0),
        right_color: tuple[int, int, int] = (0, 0, 255),
        fmt: str = "PNG",
    ) -> bytes:
        img = Image.new("RGB", size, left_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([size[0] // 2, 0, size[0] - 1, size[1] - 1], fill=right_color)
        buffer = BytesIO()
        img.save(buffer, format=fmt)
        return buffer.getvalue()

    return _create


@pytest.fixture
def project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SECRET_KEY", "test-admin-key")
    monkeypatch.setenv("API_KEY", "test-api-key")
    return SimpleNamespace(
        data_dir=data_dir,
        secret_key="test-admin-key",
        api_key="test-api-key",
    )


@pytest.fixture
def project_modules(project_env):
    import database
    import main

    importlib.reload(database)
    importlib.reload(main)
    database.create_db()
    return SimpleNamespace(database=database, main=main, env=project_env)


@pytest.fixture
def api_client(project_modules):
    with TestClient(project_modules.main.app) as client:
        yield client


@pytest.fixture
def api_headers(project_env):
    return {"X-API-Key": project_env.api_key}


@pytest.fixture
def admin_headers(project_env):
    return {"X-API-Key": project_env.api_key, "X-Admin-Key": project_env.secret_key}
