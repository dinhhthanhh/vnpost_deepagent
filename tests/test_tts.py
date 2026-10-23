import io
import json
import wave

import httpx
import pytest

from app.tts import TTSError, ZeroTTS, spoken_text


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 160)
    return output.getvalue()


@pytest.mark.parametrize(
    "mode,endpoint,key",
    [("standard", "/zero-tts/tts", "text"), ("openai", "/zero-tts/v1/audio/speech", "input")],
)
async def test_tts_postman_contract_and_base_path(settings, mode, endpoint, key):
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(200, content=wav_bytes(), headers={"Content-Type": "audio/wav"})

    client = httpx.AsyncClient(
        base_url="https://ai.vnpost.vn/zero-tts/", transport=httpx.MockTransport(transport)
    )
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    assert await adapter.synthesize("Xin chào [S1]", mode=mode) == wav_bytes()
    payload = json.loads(seen[0].content)
    assert (
        seen[0].url.path == endpoint and payload[key] == "Xin chào" and payload["voice"] == "maichi"
    )
    if mode == "openai":
        assert payload["model"] == "ZeroTTS" and payload["response_format"] == "wav"
    await client.aclose()


@pytest.mark.parametrize(
    "status,body", [(500, b"provider-secret-error"), (200, b"not wav"), (200, b"RIFFbad")]
)
async def test_tts_failures_are_sanitized(settings, status, body):
    client = httpx.AsyncClient(
        base_url="https://example.test/zero-tts/",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, content=body)),
    )
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    with pytest.raises(TTSError) as error:
        await adapter.synthesize("xin chào")
    assert "provider-secret-error" not in str(error.value)
    await client.aclose()


async def test_tts_size_limit_and_voice_contract(settings):
    def transport(request):
        if request.url.path.endswith("voices"):
            return httpx.Response(
                200, json={"total": 1, "voices": [{"name": "maichi", "is_default": True}]}
            )
        return httpx.Response(200, content=wav_bytes() * 4)

    client = httpx.AsyncClient(
        base_url="https://example.test/zero-tts/", transport=httpx.MockTransport(transport)
    )
    adapter = ZeroTTS(
        settings.model_copy(update={"tts_enabled": True, "max_audio_bytes": 1000}), client=client
    )
    assert (await adapter.voices())["voices"][0]["name"] == "maichi"
    with pytest.raises(TTSError, match="kích thước"):
        await adapter.synthesize("xin chào")
    with pytest.raises(TTSError, match="giọng"):
        await adapter.synthesize("xin chào", "../voice")
    await client.aclose()


async def test_tts_stream_is_forwarded_without_assuming_chunk_boundaries(settings):
    class Fragmented(httpx.AsyncByteStream):
        async def __aiter__(self):
            for value in wav_bytes():
                yield bytes([value])

    client = httpx.AsyncClient(
        base_url="https://example.test/zero-tts/",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Fragmented())),
    )
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    response = await adapter.open_stream("xin chào")
    assert response.request.url.path == "/zero-tts/tts/stream"
    assert b"".join([chunk async for chunk in response.aiter_bytes()]) == wav_bytes()
    await response.aclose()
    await client.aclose()


def test_speech_cleanup_does_not_read_citation_ids_or_urls():
    assert spoken_text("# Xin **chào** [S1]\n[trang](https://example.com)") == "Xin chào trang"


def test_speech_cleanup_postal_phonetics_and_decimals():
    # 1. Thuật ngữ bưu chính và thương hiệu VNPost
    text_phonetics = "VNPost cung cấp dịch vụ EMS và dịch vụ COD tra cứu qua Vpostcode hoặc BCCP."
    spoken = spoken_text(text_phonetics)
    assert "Việt Nam Pốt" in spoken
    assert "Í Em Ét" in spoken
    assert "Cê Ô Đê" in spoken
    assert "Vê Pốt Cốt" in spoken
    assert "Bê Cê Cê Pê" in spoken

    # 2. Số thập phân vs số tiền hàng nghìn
    text_decimal = "Kiện hàng nặng 1.125 kg, kích thước 2.5 cm, thể tích 0.125 lít, cước 125.000đ."
    spoken_dec = spoken_text(text_decimal)
    assert "1 phẩy 125 ki lô gam" in spoken_dec
    assert "2 phẩy 5 xăng ti mét" in spoken_dec
    assert "0 phẩy 125 lít" in spoken_dec
    assert "125000 đồng" in spoken_dec

    # 3. Phân tách cụm số mã vận đơn UPU (phúc âm từng ký tự để TTS phát âm chính xác)
    text_tracking = "Hành trình bưu gửi EB123456789VN đã phát thành công."
    spoken_track = spoken_text(text_tracking)
    assert "ê, bê" in spoken_track          # chữ E và B được đọc từng ký tự
    assert "một, hai, ba" in spoken_track   # chữ số được đọc bằng tên số tiếng Việt
    assert "vê, en" in spoken_track          # ký tự kết V và N


async def test_tts_audio_caching(settings):
    call_count = 0

    def transport(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=wav_bytes(), headers={"Content-Type": "audio/wav"})

    client = httpx.AsyncClient(
        base_url="https://ai.vnpost.vn/zero-tts/", transport=httpx.MockTransport(transport)
    )
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)

    # Lần gọi 1: Network miss
    wav1 = await adapter.synthesize("Xin chào quý khách.")
    assert wav1 == wav_bytes()
    assert call_count == 1
    stats = adapter.cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0
    assert stats["entries"] == 1

    # Lần gọi 2 với cùng nội dung: Cache hit (0 network call)
    wav2 = await adapter.synthesize("Xin chào quý khách.")
    assert wav2 == wav_bytes()
    assert call_count == 1  # Không tăng lên 2 nhờ cache
    stats2 = adapter.cache_stats()
    assert stats2["hits"] == 1
    assert stats2["misses"] == 1

    # Xóa cache
    adapter.clear_cache()
    assert adapter.cache_stats()["entries"] == 0
    await client.aclose()


def test_truncate_for_speech():
    from app.tts import truncate_for_speech

    short_text = "Chào anh chị. Chúc anh chị một ngày tốt lành."
    assert truncate_for_speech(short_text, max_chars=100) == short_text

    long_text = "Dịch vụ chuyển phát nhanh EMS. " * 30
    cut = truncate_for_speech(long_text, max_chars=100)
    assert "Anh chị xem chi tiết trên màn hình nhé." in cut
    assert len(cut) < len(long_text)
