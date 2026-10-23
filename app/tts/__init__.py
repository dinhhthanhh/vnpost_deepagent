"""Voice & Speech module: ZeroTTS, STT Transcriber, and speech preprocessing."""

from app.tts.service import TTSError, ZeroTTS, spoken_text, truncate_for_speech, validate_wav
from app.tts.stt import SpeechTranscriber, STTError

__all__ = [
    "TTSError",
    "ZeroTTS",
    "spoken_text",
    "truncate_for_speech",
    "validate_wav",
    "STTError",
    "SpeechTranscriber",
]
