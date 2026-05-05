from __future__ import annotations

from pathlib import Path

import pytest
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
