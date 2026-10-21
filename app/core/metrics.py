"""Lightweight per-request LLM telemetry for routing benchmarks."""

from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from app.core.context import current_run


class RunMetricsCallback(BaseCallbackHandler):
    """Emit provider-agnostic LLM start/end events without retaining prompts."""

    raise_error = False

    @staticmethod
    def _role(tags: list[str] | None) -> str:
        for tag in tags or []:
            if tag.startswith("role:"):
                return tag.removeprefix("role:")
        return "unknown"

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, tags=None, **kwargs):
        try:
            current_run.get().event("llm_start", call_id=str(run_id), role=self._role(tags))
        except LookupError:
            pass

    def on_llm_end(self, response, *, run_id: UUID, **kwargs):
        try:
            current_run.get().event("llm_end", call_id=str(run_id))
        except LookupError:
            pass

    def on_llm_error(self, error, *, run_id: UUID, **kwargs):
        try:
            current_run.get().event("llm_error", call_id=str(run_id), error_type=type(error).__name__)
        except LookupError:
            pass
