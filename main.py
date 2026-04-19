import json
import os
import shutil
import tempfile
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from database import DATA_DIR, create_db, get_session
from generate import generate
from models import Template, TemplateRead

STORAGE_DIR = os.path.join(DATA_DIR, "storage", "templates")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
API_KEY = os.getenv("API_KEY", "dev-api-key")


def require_api_key(x_api_key: Annotated[Optional[str], Header()] = None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


app = FastAPI(title="Paint by Numbers API", dependencies=[Depends(require_api_key)])


@app.on_event("startup")
def on_startup() -> None:
    create_db()
    os.makedirs(STORAGE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def require_admin(x_admin_key: Annotated[Optional[str], Header()] = None) -> None:
    if x_admin_key != SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _template_to_read(t: Template, base_url: str) -> TemplateRead:
    try:
        numberless: list[int] = json.loads(t.numberless_regions)
    except Exception:
        numberless = []
    return TemplateRead(
        id=t.id,
        name=t.name,
        created_at=t.created_at,
        color_count=t.color_count,
        outline_url=f"{base_url}/templates/{t.id}/outline",
        preview_url=f"{base_url}/templates/{t.id}/preview",
        palette_url=f"{base_url}/templates/{t.id}/palette",
        numberless_regions=numberless,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/templates", response_model=list[TemplateRead])
def list_templates(
    session: Session = Depends(get_session),
) -> list[TemplateRead]:
    templates = session.exec(select(Template)).all()
    return [_template_to_read(t, "") for t in templates]


@app.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(
    template_id: int,
    session: Session = Depends(get_session),
) -> TemplateRead:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_read(t, "")


@app.get("/templates/{template_id}/outline")
def get_outline(template_id: int, session: Session = Depends(get_session)) -> FileResponse:
    t = session.get(Template, template_id)
    if not t or not os.path.isfile(t.outline_path):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(t.outline_path, media_type="image/png")


@app.get("/templates/{template_id}/preview")
def get_preview(template_id: int, session: Session = Depends(get_session)) -> FileResponse:
    t = session.get(Template, template_id)
    if not t or not os.path.isfile(t.preview_path):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(t.preview_path, media_type="image/png")


@app.get("/templates/{template_id}/regions")
def get_regions(template_id: int, session: Session = Depends(get_session)) -> FileResponse:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    regions_path = os.path.join(os.path.dirname(t.outline_path), "regions.png")
    if not os.path.isfile(regions_path):
        raise HTTPException(status_code=404, detail="Regions map not available")
    return FileResponse(regions_path, media_type="image/png")


@app.get("/templates/{template_id}/palette")
def get_palette(template_id: int, session: Session = Depends(get_session)) -> dict:
    t = session.get(Template, template_id)
    if not t or not os.path.isfile(t.palette_path):
        raise HTTPException(status_code=404, detail="Template not found")
    with open(t.palette_path) as f:
        return json.load(f)


@app.delete("/admin/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    output_dir = os.path.dirname(t.outline_path)
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    session.delete(t)
    session.commit()


@app.post("/admin/upload", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
async def upload_template(
    file: UploadFile,
    colors: int = 15,
    blur: int = 4,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TemplateRead:
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    if not (2 <= colors <= 64):
        raise HTTPException(status_code=400, detail="colors must be between 2 and 64")
    if not (0 <= blur <= 10):
        raise HTTPException(status_code=400, detail="blur must be between 0 and 10")

    suffix = os.path.splitext(file.filename or "upload.jpg")[1] or ".jpg"
    name = os.path.splitext(file.filename or "upload")[0]

    # Create placeholder DB entry to get an ID before we know the output dir
    template = Template(
        name=name,
        color_count=colors,
        blur=blur,
        outline_path="",
        preview_path="",
        palette_path="",
        original_path="",
        numberless_regions="[]",
    )
    session.add(template)
    session.commit()
    session.refresh(template)

    output_dir = os.path.join(STORAGE_DIR, str(template.id))
    os.makedirs(output_dir, exist_ok=True)

    # Persist the original image alongside the processed outputs so we can
    # re-run generate() later without requiring a new upload.
    original_path = os.path.join(output_dir, f"original{suffix}")
    with open(original_path, "wb") as f_out:
        shutil.copyfileobj(file.file, f_out)

    try:
        numberless = await run_in_threadpool(generate, original_path, colors, output_dir, blur)
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        session.delete(template)
        session.commit()
        raise

    template.outline_path = os.path.join(output_dir, "outline.png")
    template.preview_path = os.path.join(output_dir, "preview.png")
    template.palette_path = os.path.join(output_dir, "palette.json")
    template.original_path = original_path
    template.numberless_regions = json.dumps(numberless)
    session.add(template)
    session.commit()
    session.refresh(template)

    return _template_to_read(template, "")


@app.post("/admin/templates/{template_id}/reprocess", response_model=TemplateRead)
async def reprocess_template(
    template_id: int,
    colors: Optional[int] = None,
    blur: Optional[int] = None,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TemplateRead:
    """Re-run image processing on a stored original without re-uploading.

    Optionally override `colors` and/or `blur`; omit to keep the original values.
    Returns 409 if the original image was not preserved (templates uploaded before
    this feature was added must be deleted and re-uploaded once).
    """
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if not t.original_path or not os.path.isfile(t.original_path):
        raise HTTPException(
            status_code=409,
            detail="Original image not available – delete and re-upload this template once to enable reprocessing",
        )

    use_colors = colors if colors is not None else t.color_count
    use_blur = blur if blur is not None else t.blur

    if not (2 <= use_colors <= 64):
        raise HTTPException(status_code=400, detail="colors must be between 2 and 64")
    if not (0 <= use_blur <= 10):
        raise HTTPException(status_code=400, detail="blur must be between 0 and 10")

    output_dir = os.path.dirname(t.outline_path)
    numberless = await run_in_threadpool(generate, t.original_path, use_colors, output_dir, use_blur)

    t.color_count = use_colors
    t.blur = use_blur
    t.numberless_regions = json.dumps(numberless)
    t.outline_path = os.path.join(output_dir, "outline.png")
    t.preview_path = os.path.join(output_dir, "preview.png")
    t.palette_path = os.path.join(output_dir, "palette.json")
    session.add(t)
    session.commit()
    session.refresh(t)

    return _template_to_read(t, "")
