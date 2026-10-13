import asyncio
import io
import re
import wave

import httpx

from app.config import Settings


class TTSError(Exception):
    pass


def spoken_text(text: str) -> str:
    text = re.sub(r"\[S\d+\]", "", text)
    text = re.sub(r"```[\s\S]*?```", " [Đoạn mã được hiển thị trong câu trả lời.] ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*[#>*-]+\s*", "", text)
    # Chuẩn hóa ngày tháng dạng dd/mm/yyyy -> ngày dd tháng mm năm yyyy
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", r"ngày \1 tháng \2 năm \3", text)
    # Chuẩn hóa số điện thoại / hotline có dấu chấm phân cách
    text = re.sub(r"(\d{4})\.(\d{2})\.(\d{2})\.(\d{2})", r"\1 \2 \3 \4", text)
    text = text.replace("|", ", ").replace("`", "").replace("**", "").replace("*", "")
    return re.sub(r"\s+", " ", text).strip()


def validate_wav(data: bytes):
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if audio.getnchannels() < 1 or audio.getnframes() == 0 or audio.getsampwidth() != 2:
                raise TTSError("TTS trả về WAV không hợp lệ hoặc không phải PCM 16-bit.")
    except (wave.Error, EOFError) as exc:
        raise TTSError("TTS không trả về file WAV hợp lệ.") from exc


class ZeroTTS:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        headers = {"ngrok-skip-browser-warning": "true"}
        if settings.tts_api_key.get_secret_value():
            headers["Authorization"] = "Bearer " + settings.tts_api_key.get_secret_value()
        self.client = client or httpx.AsyncClient(base_url=settings.tts_base_url.rstrip("/") + "/",
                                                 headers=headers, follow_redirects=False,
                                                 timeout=httpx.Timeout(settings.tts_timeout_seconds, connect=10),
                                                 limits=httpx.Limits(max_connections=settings.max_parallel_tts,
                                                                     max_keepalive_connections=settings.max_parallel_tts))
        self.owns_client = client is None
        self.last_health = "disabled" if not settings.tts_enabled else "unknown"

    def payload(self, text: str, voice: str | None, mode: str):
        if not self.settings.tts_enabled:
            raise TTSError("TTS chưa bật; cấu hình TTS_ENABLED=true.")
        text = spoken_text(text)
        if not text:
            raise TTSError("Không có nội dung để đọc.")
        if len(text) > self.settings.max_tts_characters:
            raise TTSError("Câu trả lời vượt giới hạn đọc; hãy yêu cầu tóm tắt để nghe.")
        voice = voice or self.settings.tts_voice
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", voice):
            raise TTSError("Tên giọng không hợp lệ.")
        if mode == "openai":
            return "v1/audio/speech", {"model": "ZeroTTS", "input": text, "voice": voice,
                                        "response_format": "wav", "speed": 1.0}
        return "tts", {"text": text, "voice": voice, "cfg_scale": 1.0, "audio_temperature": 0.8}

    async def synthesize(self, text: str, voice: str | None = None, mode: str | None = None) -> bytes:
        endpoint, payload = self.payload(text, voice, mode or self.settings.tts_mode)
        chunks, size = [], 0
        try:
            async with asyncio.timeout(self.settings.tts_timeout_seconds):
                async with self.client.stream("POST", endpoint, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_audio_bytes:
                            raise TTSError("Âm thanh vượt giới hạn kích thước.")
                        chunks.append(chunk)
        except (httpx.HTTPError, TimeoutError) as exc:
            self.last_health = "unavailable"
            raise TTSError("Không kết nối được ZeroTTS hoặc dịch vụ từ chối yêu cầu.") from exc
        data = b"".join(chunks)
        validate_wav(data)
        self.last_health = "available"
        return data

    async def voices(self) -> dict:
        if not self.settings.tts_enabled:
            return {"enabled": False, "voices": []}
        try:
            response = await self.client.get("voices")
            response.raise_for_status()
            data = response.json()
            return {"enabled": True, "voices": data.get("voices", [])}
        except (httpx.HTTPError, ValueError) as exc:
            raise TTSError("Không lấy được danh sách giọng đọc.") from exc

    async def open_stream(self, text: str, voice: str | None = None):
        _, payload = self.payload(text, voice, "standard")
        try:
            response = await self.client.send(self.client.build_request("POST", "tts/stream", json=payload), stream=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if "response" in locals():
                await response.aclose()
            raise TTSError("Không mở được luồng âm thanh ZeroTTS.") from exc
        return response

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
