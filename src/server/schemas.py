"""Pydantic request/response schemas for API endpoints."""
from typing import List, Optional
from pydantic import BaseModel


class GameStartRequest(BaseModel):
    init_npc_num: int
    sect_num: int
    protagonist: str
    npc_awakening_rate_per_month: float
    world_history: Optional[str] = None


class SetObjectiveRequest(BaseModel):
    avatar_id: str
    content: str


class ClearObjectiveRequest(BaseModel):
    avatar_id: str


class CreateAvatarRequest(BaseModel):
    surname: Optional[str] = None
    given_name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    level: Optional[int] = None
    sect_id: Optional[int] = None
    persona_ids: Optional[List[int]] = None
    pic_id: Optional[int] = None
    technique_id: Optional[int] = None
    weapon_id: Optional[int] = None
    auxiliary_id: Optional[int] = None
    alignment: Optional[str] = None
    appearance: Optional[int] = None
    relations: Optional[List[dict]] = None


class DeleteAvatarRequest(BaseModel):
    avatar_id: str


class SetPhenomenonRequest(BaseModel):
    id: int


class LanguageRequest(BaseModel):
    lang: str


class LLMConfigDTO(BaseModel):
    base_url: str
    api_key: Optional[str] = ""
    model_name: str
    fast_model_name: str
    mode: str
    max_concurrent_requests: Optional[int] = 10


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = ""
    model_name: str


class SaveGameRequest(BaseModel):
    custom_name: Optional[str] = None  # 自定义存档名称


class DeleteSaveRequest(BaseModel):
    filename: str


class LoadGameRequest(BaseModel):
    filename: str
