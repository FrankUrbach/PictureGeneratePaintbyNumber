from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


def _upload_template(api_client, admin_headers, image_bytes: bytes, *, filename: str = "input.png", colors: int = 2, blur: int = 0):
    return api_client.post(
        f"/admin/upload?colors={colors}&blur={blur}",
        files={"file": (filename, image_bytes, "image/png")},
        headers=admin_headers,
    )


def test_api_requires_api_key(api_client) -> None:
    response = api_client.get("/templates")

    assert response.status_code == 401


def test_upload_and_serve_template_assets(api_client, admin_headers, api_headers, image_bytes_factory, project_env) -> None:
    image_bytes = image_bytes_factory()
    response = _upload_template(api_client, admin_headers, image_bytes)

    assert response.status_code == 201
    payload = response.json()
    template_id = payload["id"]
    assert payload["name"] == "input"
    assert payload["color_count"] == 2
    assert payload["outline_url"] == f"/templates/{template_id}/outline"
    assert payload["preview_url"] == f"/templates/{template_id}/preview"
    assert payload["palette_url"] == f"/templates/{template_id}/palette"
    assert isinstance(payload["numberless_regions"], list)

    templates = api_client.get("/templates", headers=api_headers)
    assert templates.status_code == 200
    assert len(templates.json()) == 1

    detail = api_client.get(f"/templates/{template_id}", headers=api_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == template_id

    for route in ("outline", "preview", "regions"):
        resp = api_client.get(f"/templates/{template_id}/{route}", headers=api_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    palette = api_client.get(f"/templates/{template_id}/palette", headers=api_headers)
    assert palette.status_code == 200
    assert palette.headers["content-type"].startswith("application/json")
    assert set(palette.json().keys()) == {"1", "2"}

    output_dir = project_env.data_dir / "storage" / "templates" / str(template_id)
    assert (output_dir / "outline.png").is_file()
    assert (output_dir / "preview.png").is_file()
    assert (output_dir / "palette.json").is_file()
    assert (output_dir / "regions.png").is_file()

    with Image.open(output_dir / "preview.png") as preview:
        assert preview.size == (128, 128)


def test_reprocess_and_delete_template(api_client, admin_headers, api_headers, image_bytes_factory, project_env) -> None:
    response = _upload_template(api_client, admin_headers, image_bytes_factory())
    template_id = response.json()["id"]

    reprocess = api_client.post(
        f"/admin/templates/{template_id}/reprocess?colors=2&blur=1",
        headers=admin_headers,
    )
    assert reprocess.status_code == 200
    assert reprocess.json()["color_count"] == 2

    detail = api_client.get(f"/templates/{template_id}", headers=api_headers)
    assert detail.status_code == 200
    assert detail.json()["color_count"] == 2

    delete = api_client.delete(f"/admin/templates/{template_id}", headers=admin_headers)
    assert delete.status_code == 204

    missing = api_client.get(f"/templates/{template_id}", headers=api_headers)
    assert missing.status_code == 404

    output_dir = project_env.data_dir / "storage" / "templates" / str(template_id)
    assert not output_dir.exists()


def test_admin_upload_rejects_unsupported_file_type(api_client, admin_headers) -> None:
    response = api_client.post(
        "/admin/upload?colors=2&blur=0",
        files={"file": ("input.txt", b"not-an-image", "text/plain")},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type"
