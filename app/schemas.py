import ipaddress
import socket
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Kiểm tra xem địa chỉ IP có thuộc dải cấm (private, loopback, link-local, reserved, multicast, unspecified)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_safe_url(
    url: str,
    *,
    allowed_domains: set[str] | None = None,
    allowed_schemes: set[str] = {"http", "https"},
) -> str:
    """Xác thực URL an toàn chống SSRF:
    - Kiểm tra giao thức (chỉ http/https).
    - Kiểm tra tên miền theo danh sách cho phép (nếu có).
    - Phân giải DNS và kiểm tra fail-closed mọi địa chỉ IP, chặn private/loopback/link-local/metadata IP.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL không được để trống")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in allowed_schemes:
        raise ValueError(f"Giao thức URL không hợp lệ (chỉ chấp nhận {', '.join(sorted(allowed_schemes))})")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL không có hostname hợp lệ")

    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("Không cho phép URL trỏ về máy chủ nội bộ (SSRF)")

    if allowed_domains:
        domain_match = any(host == d or host.endswith("." + d) for d in allowed_domains)
        if not domain_match:
            raise ValueError(f"Tên miền '{host}' không nằm trong danh sách cho phép ({', '.join(sorted(allowed_domains))})")

    # 1. Kiểm tra trực tiếp nếu host là chuỗi biểu diễn IP
    parsed_ip = None
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        parsed_ip = None

    if parsed_ip is not None:
        if is_blocked_ip(parsed_ip):
            raise ValueError("Không cho phép URL trỏ về mạng nội bộ hoặc dải IP cấm (SSRF)")
    else:
        # 2. Phân giải DNS và kiểm tra tất cả các IP trả về
        try:
            addr_info = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ValueError(f"Không thể phân giải tên miền: {host}") from exc

        if not addr_info:
            raise ValueError(f"Không thể phân giải địa chỉ IP cho: {host}")

        for _, _, _, _, sockaddr in addr_info:
            try:
                res_ip = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                raise ValueError(f"Địa chỉ IP phân giải không hợp lệ: {sockaddr[0]}")
            if is_blocked_ip(res_ip):
                raise ValueError(f"Không cho phép URL trỏ về mạng nội bộ ({res_ip}) (SSRF)")

    return url


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    image: str | None = Field(None, max_length=15_000_000)
    session_id: UUID | None = None
    grounded: bool = True
    mode: Literal["auto", "fast", "deep"] = "auto"
    voice: bool = False
    # The web client can synthesize completed text fragments itself through the
    # streaming TTS endpoint. Keep this opt-in so API consumers retain the
    # existing single-WAV behaviour.
    stream_voice: bool = False
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
        if value.startswith("data:image/"):
            return value
        if value.startswith(("http://", "https://")):
            return validate_safe_url(value)
        raise ValueError("Ảnh phải là định dạng data URL (data:image/...) hoặc liên kết http(s)")



class Source(BaseModel):
    citation_id: str
    document_id: str
    filename: str
    location: str
    chunk_id: str
    excerpt: str
    retrieval_score: float
    is_global: bool = True
    authority: Literal["vnpost_internal", "official_public", "user_upload", "legacy_unverified"] = "legacy_unverified"
    source_url: str | None = None
    issuer: str | None = None
    session_id: str | None = None


class TaskSpec(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    agent: Literal["rag-agent", "analyst-agent", "writer-agent", "tracking-agent", "post-office-agent"]
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
    voice: str | None = Field("maichi", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    mode: Literal["standard", "openai"] | None = None
    cfg_scale: float = Field(1.0, ge=0.5, le=2.5)
    audio_temperature: float = Field(0.8, ge=0.1, le=1.5)
    text_temperature: float = Field(1.0, ge=0.1, le=1.5)
    audio_topk: int = Field(25, ge=1, le=100)
    audio_topp: float = Field(0.95, ge=0.1, le=1.0)
    audio_repetition_penalty: float = Field(1.2, ge=1.0, le=2.0)
    speed: float = Field(1.0, ge=0.5, le=2.0)


class S3IngestRequest(BaseModel):
    url: str | None = Field(None, description="S3 Presigned GET URL hoặc liên kết tải tài liệu trực tiếp")
    bucket: str | None = Field(None, description="Tên S3 Bucket nếu dùng kết nối trực tiếp")
    key: str | None = Field(None, description="S3 Object Key/Path nếu dùng kết nối trực tiếp")
    filename: str | None = Field(None, description="Tên file hiển thị (ví dụ: bang_cuoc_2025.pdf)")
    is_global: bool = True
    authority: Literal["vnpost_internal", "official_public", "user_upload"] = "official_public"
    source_url: str | None = None
    issuer: str | None = "Vietnam Post"
    session_id: str | None = None
    user_id: str | None = None

    @field_validator("url")
    @classmethod
    def valid_s3_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        return validate_safe_url(value)
