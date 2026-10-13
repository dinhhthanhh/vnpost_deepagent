from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    image: str | None = Field(None, max_length=15_000_000)
    session_id: UUID | None = None
    grounded: bool = True
    mode: Literal["auto", "fast", "deep"] = "auto"
    voice: bool = False
    voice_name: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value):
        if not value.strip():
            raise ValueError("Câu hỏi không được để trống")
        return value

    @field_validator("image")
    @classmethod
    def valid_image(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not (value.startswith("data:image/") or value.startswith(("http://", "https://"))):
            raise ValueError("Ảnh phải là định dạng data URL (data:image/...) hoặc liên kết http(s)")
        return value


class Source(BaseModel):
    citation_id: str
    document_id: str
    filename: str
    location: str
    chunk_id: str
    excerpt: str
    retrieval_score: float


class TaskSpec(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    agent: Literal["rag-agent", "analyst-agent", "writer-agent"]
    description: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    answer: str
    sources: list[Source]
    grounding_status: str
    route: str = "deep"
    route_reason: str = ""
    elapsed_ms: int
    events: list[dict]
    audio_url: str | None = None
    warnings: list[str] = Field(default_factory=list)



class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voice: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    mode: Literal["standard", "openai"] | None = None
