from pydantic import BaseModel, Field
from typing import Optional, Generic, TypeVar, List, Any
from datetime import datetime

T = TypeVar("T")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: Optional[str] = None


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Operation successful"
    data: Optional[T] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Operation successful"
    data: List[T]
    total: int
    page: int
    per_page: int
    total_pages: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
