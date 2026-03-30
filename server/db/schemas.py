from datetime import datetime
from pydantic import BaseModel


class RecordCreate(BaseModel):
    title: str
    description: str = ""
    tags: str = ""


class RecordUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: str | None = None


class RecordOut(BaseModel):
    id: int
    title: str
    description: str
    tags: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TagValueOut(BaseModel):
    tag_id: str
    tag_name: str
    value: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class TagHistoryOut(BaseModel):
    id: int
    tag_id: int | None = None
    tag_name: str = ""
    value: str
    recorded_at: datetime

    model_config = {"from_attributes": True}
