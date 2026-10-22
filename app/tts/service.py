import asyncio
import collections
import hashlib
import io
import re
import wave

import httpx

from app.core.config import Settings


class TTSError(Exception):
    pass


# Từ điển chuyển đổi ngữ âm chuyên ngành bưu chính VNPost sang văn phong nói tự nhiên
POSTAL_PHONETICS: list[tuple[re.Pattern, str]] = [
    # Tên thương hiệu và định danh VNPost
    (re.compile(r"\b(?:VNPost|Vietnam\s*Post|Vnpost)\b", re.IGNORECASE), "Việt Nam Pốt"),
    # Dịch vụ cốt lõi & viết tắt nghiệp vụ
    (re.compile(r"\bEMS\b"), "Í Em Ét"),
    (re.compile(r"\bCOD\b"), "Cê Ô Đê"),
    (re.compile(r"\bVpostcode\b", re.IGNORECASE), "Vê Pốt Cốt"),
    (re.compile(r"\bBCCP\b"), "Bê Cê Cê Pê"),
    (re.compile(r"\bUPU\b"), "U Pê U"),
    (re.compile(r"\bCSKH\b"), "Chăm sóc khách hàng"),
    (re.compile(r"\bTCT\b"), "Tổng công ty"),
    (re.compile(r"\bSĐT\b", re.IGNORECASE), "Số điện thoại"),
    (re.compile(r"\bĐKCL\b"), "Đo kiểm chất lượng"),
    (re.compile(r"\bKT1\b", re.IGNORECASE), "Kê Tê một"),
    (re.compile(r"\bHITL\b"), "Xác nhận của con người"),
    (re.compile(r"\bTP\.?\s*HCM\b", re.IGNORECASE), "Thành phố Hồ Chí Minh"),
    (re.compile(r"\bTP\.?\s*HN\b", re.IGNORECASE), "Thành phố Hà Nội"),
]


def spoken_text(text: str) -> str:
    # 1. Xóa mã trích dẫn [S1], [S2]... và khối code
    text = re.sub(r"\[S\d+\]", "", text)
    text = re.sub(r"```[\s\S]*?```", " Đoạn mã được hiển thị trong câu trả lời. ", text)
    # 2. Xóa dòng kẻ phân cách bảng Markdown (ví dụ: | --- | :---: | --- |) trước khi thay dấu |
    text = re.sub(r"(?m)^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$", " ", text)
    # 3. Chuyển link Markdown [text](url) thành text và xóa URL trần
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*[#>*-]+\s*", "", text)
    # 4. Chuẩn hóa ngày tháng dd/mm/yyyy và khoảng số (ví dụ: 24-36 giờ -> 24 đến 36 giờ)
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", r"ngày \1 tháng \2 năm \3", text)
    text = re.sub(
        r"\b(\d+)\s*-\s*(\d+)\s*(giờ|ngày|tuần|tháng|năm|kg|g|gam|đồng)\b",
        r"\1 đến \2 \3",
        text,
        flags=re.IGNORECASE,
    )

    # 5. Phân biệt số thập phân (đơn vị đo lường) vs số tiền hàng nghìn (1.125 kg -> 1 phẩy 125 ki lô gam)
    text = re.sub(
        r"\b(\d+)[.,](\d{1,4})\s*(?:đ/kg|đồng/kg)\b",
        r"\1 phẩy \2 đồng một ki lô gam",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(\d+)[.,](\d{1,4})\s*kg\b", r"\1 phẩy \2 ki lô gam", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"\b(\d+)[.,](\d{1,4})\s*g(?:am)?\b", r"\1 phẩy \2 gam", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"\b(\d+)[.,](\d{1,4})\s*cm\b", r"\1 phẩy \2 xăng ti mét", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\b(\d+)[.,](\d{1,4})\s*m\b", r"\1 phẩy \2 mét", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(\d+)[.,](\d{1,4})\s*km\b", r"\1 phẩy \2 ki lô mét", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\b(\d+)[.,](\d{1,4})\s*tấn\b", r"\1 phẩy \2 tấn", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)[.,](\d{1,4})\s*lít\b", r"\1 phẩy \2 lít", text, flags=re.IGNORECASE)
    # Số thập phân bắt đầu bằng 0 (ví dụ: 0.125 hoặc 0.5)
    text = re.sub(r"\b0[.,](\d+)\b", r"0 phẩy \1", text)

    # 6. Chuẩn hóa số tiền Việt Nam (125.000đ -> 125000 đồng) và đơn vị số nguyên
    text = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", text)
    text = re.sub(
        r"\b(\d+)\s*(?:đ/kg|đồng/kg)\b", r"\1 đồng một ki lô gam", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\b(\d+)\s*(?:đ|vnđ|vnd)\b", r"\1 đồng", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*kg\b", r"\1 ki lô gam", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*g\b", r"\1 gam", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*cm\b", r"\1 xăng ti mét", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*m\b", r"\1 mét", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*km\b", r"\1 ki lô mét", text, flags=re.IGNORECASE)

    # 7. Tách mã vận đơn UPU (ví dụ EB123456789VN -> EB 123 456 789 VN) để TTS đọc rõ từng cụm số
    text = re.sub(r"\b([A-Za-z]{2})(\d{3})(\d{3})(\d{3})([A-Za-z]{2})\b", r"\1 \2 \3 \4 \5", text)

    # 8. Áp dụng từ điển phiên âm ngữ âm bưu chính
    for pattern, phonetic in POSTAL_PHONETICS:
        text = pattern.sub(phonetic, text)

    # 9. Chuẩn hóa số điện thoại / hotline có dấu chấm hoặc khoảng cách
    text = re.sub(r"(\d{4})\.(\d{2,3})\.(\d{2,3})", r"\1 \2 \3", text)
    text = re.sub(r"\b(1900|1800)\s+(\d{2,4})\s+(\d{2,4})\b", r"\1 \2 \3", text)

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
        self.client = client or httpx.AsyncClient(
            base_url=settings.tts_base_url.rstrip("/") + "/",
            headers=headers,
            follow_redirects=False,
            timeout=httpx.Timeout(settings.tts_timeout_seconds, connect=10),
            limits=httpx.Limits(
                max_connections=settings.max_parallel_tts,
                max_keepalive_connections=settings.max_parallel_tts,
            ),
        )
        self.owns_client = client is None
        self.last_health = "disabled" if not settings.tts_enabled else "unknown"

        # Audio memory cache (LRU) để tránh gọi lại ZeroTTS server với các câu nói lặp lại
        self._cache: collections.OrderedDict[str, bytes] = collections.OrderedDict()
        self.max_cache_entries = 128
        self.cache_hits = 0
        self.cache_misses = 0

    def cache_key(self, text: str, voice: str | None, mode: str, kwargs: dict) -> str:
        spoken = spoken_text(text)
        raw = f"{voice or self.settings.tts_voice}|{mode}|{spoken}|{sorted(kwargs.items())}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def cache_stats(self) -> dict:
        return {
            "entries": len(self._cache),
            "max_entries": self.max_cache_entries,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
        }

    def clear_cache(self):
        self._cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0

    def payload(self, text: str, voice: str | None, mode: str, **kwargs):
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
            return "v1/audio/speech", {
                "model": "ZeroTTS",
                "input": text,
                "voice": voice,
                "response_format": "wav",
                "speed": kwargs.get("speed", 1.0),
            }
        return "tts", {
            "text": text,
            "voice": voice,
            "cfg_scale": kwargs.get("cfg_scale", 1.0),
            "audio_temperature": kwargs.get("audio_temperature", 0.8),
            "audio_repetition_penalty": kwargs.get("audio_repetition_penalty", 1.2),
            "audio_topk": kwargs.get("audio_topk", 25),
            "audio_topp": kwargs.get("audio_topp", 0.95),
        }

    async def synthesize(
        self, text: str, voice: str | None = None, mode: str | None = None, **kwargs
    ) -> bytes:
        effective_mode = mode or self.settings.tts_mode
        key = self.cache_key(text, voice, effective_mode, kwargs)
        if key in self._cache:
            self.cache_hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]

        self.cache_misses += 1
        endpoint, payload = self.payload(text, voice, effective_mode, **kwargs)
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

        # Cất vào cache
        if len(self._cache) >= self.max_cache_entries:
            self._cache.popitem(last=False)
        self._cache[key] = data

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

    async def open_stream(self, text: str, voice: str | None = None, **kwargs):
        _, payload = self.payload(text, voice, "standard", **kwargs)
        try:
            response = await self.client.send(
                self.client.build_request("POST", "tts/stream", json=payload), stream=True
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if "response" in locals():
                await response.aclose()
            raise TTSError("Không mở được luồng âm thanh ZeroTTS.") from exc
        return response

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
