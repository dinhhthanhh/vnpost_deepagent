"""Voice & Speech module: ZeroTTS, STT Transcriber, and speech preprocessing."""

from app.tts.service import TTSError, ZeroTTS, spoken_text, validate_wav
from app.tts.stt import STTError, SpeechTranscriber

__all__ = [
    "TTSError",
    "ZeroTTS",
    "spoken_text",
    "validate_wav",
    "STTError",
    "SpeechTranscriber",
]
