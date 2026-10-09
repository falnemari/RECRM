from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")

class BaseMeta(BaseModel):
    request_id: Optional[str] = None

class CollectionMeta(BaseMeta):
    page: int = 1
    page_size: int = 50
    total: int = 0

class ResponseEnvelope(BaseModel, Generic[DataT]):
    data: DataT
    meta: BaseMeta = Field(default_factory=BaseMeta)

class CollectionEnvelope(BaseModel, Generic[DataT]):
    data: List[DataT]
    meta: CollectionMeta

class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    fields: Optional[Dict[str, List[str]]] = None

class ErrorEnvelope(BaseModel):
    error: ErrorDetail

