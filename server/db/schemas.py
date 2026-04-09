from datetime import datetime
from pydantic import BaseModel


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


class CheckoutOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None = None

    model_config = {"from_attributes": True}
