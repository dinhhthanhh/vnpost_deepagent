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


@pytest.mark.parametrize("mode,endpoint,key", [("standard", "/zero-tts/tts", "text"), ("openai", "/zero-tts/v1/audio/speech", "input")])
async def test_tts_postman_contract_and_base_path(settings, mode, endpoint, key):
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(200, content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    client = httpx.AsyncClient(base_url="https://ai.vnpost.vn/zero-tts/", transport=httpx.MockTransport(transport))
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    assert await adapter.synthesize("Xin chào [S1]", mode=mode) == wav_bytes()
    payload = json.loads(seen[0].content)
    assert seen[0].url.path == endpoint and payload[key] == "Xin chào" and payload["voice"] == "maichi"
    if mode == "openai":
        assert payload["model"] == "ZeroTTS" and payload["response_format"] == "wav"
    await client.aclose()


@pytest.mark.parametrize("status,body", [(500, b"provider-secret-error"), (200, b"not wav"), (200, b"RIFFbad")])
async def test_tts_failures_are_sanitized(settings, status, body):
    client = httpx.AsyncClient(base_url="https://example.test/zero-tts/", transport=httpx.MockTransport(lambda r: httpx.Response(status, content=body)))
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    with pytest.raises(TTSError) as error:
        await adapter.synthesize("xin chào")
    assert "provider-secret-error" not in str(error.value)
    await client.aclose()


async def test_tts_size_limit_and_voice_contract(settings):
    def transport(request):
        if request.url.path.endswith("voices"):
            return httpx.Response(200, json={"total": 1, "voices": [{"name": "maichi", "is_default": True}]})
        return httpx.Response(200, content=wav_bytes() * 4)
    client = httpx.AsyncClient(base_url="https://example.test/zero-tts/", transport=httpx.MockTransport(transport))
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True, "max_audio_bytes": 1000}), client=client)
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
    client = httpx.AsyncClient(base_url="https://example.test/zero-tts/", transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Fragmented())))
    adapter = ZeroTTS(settings.model_copy(update={"tts_enabled": True}), client=client)
    response = await adapter.open_stream("xin chào")
    assert response.request.url.path == "/zero-tts/tts/stream"
    assert b"".join([chunk async for chunk in response.aiter_bytes()]) == wav_bytes()
    await response.aclose()
    await client.aclose()


def test_speech_cleanup_does_not_read_citation_ids_or_urls():
    assert spoken_text("# Xin **chào** [S1]\n[trang](https://example.com)") == "Xin chào trang"
