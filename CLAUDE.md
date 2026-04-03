# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

A Python backend that converts images into paint-by-numbers templates and exposes them via a REST API for an iPhone app.

Pipeline: `[Admin Image Upload] → [Image Processing] → [Storage] → [API] → [iPhone App]`

## Implementation Order (from ROADMAP.md)

1. `generate.py` – Image processing algorithm
2. Test with a real image and verify results
3. `main.py` – FastAPI app with all endpoints
4. `models.py` + `database.py` – SQLite database layer
5. `requirements.txt` + `Dockerfile` – Deployment prep
6. Integration test: upload image via API, verify output

## Running the Project

```bash
# Image processing (standalone test)
python generate.py --input meinbild.jpg --colors 15 --output ./output/

# API server
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Architecture

### Image Processing (`generate.py`)
1. Resize input image to max 1000px width, convert to RGB
2. K-Means clustering (k=10–20, configurable) to reduce colors
3. Connected components to find same-color regions; remove small regions (noise)
4. Draw black borders between regions → outline image
5. Number each color region (font size scales with region size)
6. Output: `outline.png`, `preview.png`, `palette.json`

### REST API (`main.py`)
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/templates` | List all templates |
| `GET` | `/templates/{id}` | Template details + URLs |
| `GET` | `/templates/{id}/outline` | Outline PNG |
| `GET` | `/templates/{id}/preview` | Preview PNG |
| `GET` | `/templates/{id}/palette` | Color palette JSON |
| `POST` | `/admin/upload` | Upload and process new image (async) |

### Database Model (`models.py`)
```python
class Template(SQLModel, table=True):
    id: int
    name: str
    created_at: datetime
    color_count: int
    outline_path: str
    preview_path: str
    palette_path: str
```

### File Storage
```
storage/templates/{id}/outline.png
storage/templates/{id}/preview.png
storage/templates/{id}/palette.json
```

## Key Dependencies
- `opencv-python` – image processing, edge detection
- `scikit-learn` – K-Means clustering
- `numpy` – array operations
- `Pillow` – image I/O and drawing
- `FastAPI` + `uvicorn` – REST API
- `SQLModel` – SQLite ORM

## Deployment (Railway.app)
Uses `Dockerfile` with `python:3.11-slim`. Environment variable `SECRET_KEY` protects the admin upload endpoint. Railway generates a public URL to configure in the iPhone app.

## Quality Goals
- Color reduction must look natural (no harsh color jumps)
- Regions must be large enough to paint (minimum size configurable)
- Numbers must be legible (font size proportional to region size)
- GET endpoint response times < 200ms
- Upload + processing: 10–30 seconds is acceptable (handle async)
