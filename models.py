from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Template(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    color_count: int
    outline_path: str
    preview_path: str
    palette_path: str
    original_path: str = Field(default="")
    blur: int = Field(default=4)
    # JSON-encoded list[int] of color numbers that have regions too thin for a number
    numberless_regions: str = Field(default="[]")


class TemplateRead(SQLModel):
    id: int
    name: str
    created_at: datetime
    color_count: int
    outline_url: str
    preview_url: str
    palette_url: str
    # Color numbers where at least one region has no printed number.
    # Existing iOS app ignores unknown JSON keys, so this is backward-compatible.
    numberless_regions: list[int] = []
