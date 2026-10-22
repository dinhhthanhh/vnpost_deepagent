"""Explicit live probe. Sends only a short synthetic tool-calling test, no KB documents."""
import argparse
import asyncio
import json

from langchain_core.tools import tool

from app.agents import create_model
from app.core.config import Settings
from app.rag import make_embedding
from app.tts import ZeroTTS

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true", help="Make real upstream API requests")
parser.add_argument("--tts", action="store_true", help="Also call configured ZeroTTS /tts")
args = parser.parse_args()
if not args.live:
    raise SystemExit("Add --live to explicitly test real services (may use API quota)")


@tool
def probe(value: str) -> str:
    """Echo the requested test value."""
    return value


async def main():
    settings = Settings()
    report = {}
    try:
        model = create_model(settings, "supervisor").bind_tools([probe], tool_choice="probe")
        answer = await model.ainvoke("Call probe with value ready. This is a synthetic connectivity test.")
        report["llm_tool_calling"] = bool(answer.tool_calls and answer.tool_calls[0]["name"] == "probe")
    except Exception as exc:
        report["llm_tool_calling"] = False
        report["llm_error_type"] = type(exc).__name__
    try:
        vector = await asyncio.to_thread(make_embedding(settings).get_query_embedding, "Kiểm tra kết nối")
        report["embedding_dimensions"] = len(vector)
    except Exception as exc:
        report["embedding_error_type"] = type(exc).__name__
    if args.tts:
        tts = ZeroTTS(settings)
        try:
            audio = await tts.synthesize("Xin chào. Đây là câu kiểm tra kết nối.")
            report["tts_wav_bytes"] = len(audio)
        except Exception as exc:
            report["tts_error_type"] = type(exc).__name__
        finally:
            await tts.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("llm_tool_calling") or not report.get("embedding_dimensions") or (args.tts and not report.get("tts_wav_bytes")):
        raise SystemExit(1)


asyncio.run(main())
