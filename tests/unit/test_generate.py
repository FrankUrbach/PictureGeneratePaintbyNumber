from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from generate import _load_number_font, build_outline_aa, generate, smooth_labels


def test_smooth_labels_blur_zero_returns_input() -> None:
    label_img = np.array([[0, 1], [1, 0]], dtype=np.int32)

    result = smooth_labels(label_img, radius=0)

    np.testing.assert_array_equal(result, label_img)


def test_build_outline_aa_does_not_wrap_edges() -> None:
    label_img = np.zeros((16, 16), dtype=np.int32)
    label_img[-4:, :] = 1

    border_aa, _ = build_outline_aa(label_img, scale=1)

    assert border_aa[:3, :].max() == 0
    assert border_aa[-6:, :].max() > 0


def test_load_number_font_falls_back_when_system_fonts_are_unavailable(monkeypatch) -> None:
    _load_number_font.cache_clear()
    monkeypatch.setattr("generate.os.path.isfile", lambda _: False)

    font = _load_number_font(12)

    assert font is not None
    assert hasattr(font, "getmask")


def test_generate_creates_expected_outputs(tmp_path: Path, image_factory) -> None:
    input_path = image_factory(tmp_path / "input.png")
    output_dir = tmp_path / "output"

    numberless = generate(str(input_path), n_colors=2, output_dir=str(output_dir), blur=0, scale=1)

    assert numberless == [] or all(isinstance(i, int) for i in numberless)

    for filename in ("outline.png", "preview.png", "palette.json", "regions.png"):
        assert (output_dir / filename).is_file()

    with Image.open(output_dir / "preview.png") as preview:
        assert preview.size == (64, 64)

    palette = json.loads((output_dir / "palette.json").read_text())
    assert set(palette.keys()) == {"1", "2"}
