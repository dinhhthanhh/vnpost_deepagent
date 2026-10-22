import io

import pytest
from starlette.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.tts.stt import SpeechTranscriber, STTError


@pytest.mark.asyncio
async def test_speech_transcriber_unit(settings):
    """Kiểm tra SpeechTranscriber đơn vị: xử lý âm thanh, phát hiện lỗi âm thanh trống và fallback."""
    transcriber = SpeechTranscriber(settings)

    # 1. Âm thanh trống -> raise STTError
    with pytest.raises(STTError) as exc:
        await transcriber.transcribe(b"")
    assert "trống" in str(exc.value)

    # 2. Âm thanh hợp lệ -> Chuyển đổi thành văn bản tiếng Việt
    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 300
    res = await transcriber.transcribe(dummy_wav, filename="test.wav", content_type="audio/wav")
    assert res["status"] == "ok"
    assert res["language"] == "vi"
    assert len(res["text"]) > 0

    # 3. Khi STT bị tắt qua cấu hình
    settings_disabled = Settings(stt_enabled=False)
    transcriber_disabled = SpeechTranscriber(settings_disabled)
    with pytest.raises(STTError) as exc_dis:
        await transcriber_disabled.transcribe(dummy_wav)
    assert "tắt" in str(exc_dis.value)


@pytest.mark.asyncio
async def test_api_voice_transcribe_endpoint(settings):
    """Kiểm tra endpoint HTTP POST /api/voice/transcribe."""
    with TestClient(create_app(settings)) as client:
        # 1. Gửi tệp âm thanh hợp lệ
        fake_audio = b"RIFF" + b"\x00" * 36 + b"data" + b"EB123456789VN" * 20
        files = {"file": ("recording.wav", io.BytesIO(fake_audio), "audio/wav")}
        resp = client.post("/api/voice/transcribe", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "text" in data
        assert len(data["text"]) > 0

        # 2. Gửi tệp trống -> 422
        empty_files = {"file": ("empty.wav", io.BytesIO(b""), "audio/wav")}
        resp_empty = client.post("/api/voice/transcribe", files=empty_files)
        assert resp_empty.status_code == 422
