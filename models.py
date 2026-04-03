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


class TemplateRead(SQLModel):
    id: int
    name: str
    created_at: datetime
    color_count: int
    outline_url: str
    preview_url: str
    palette_url: str
