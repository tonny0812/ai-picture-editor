import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import Role


class AdminUserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: Role
    created_at: datetime

    model_config = {"from_attributes": True}


class RolePatchIn(BaseModel):
    role: Role
