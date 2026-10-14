import json
import re
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    demo_mode: bool | None = None
    router_enabled: bool = Field(False, validation_alias=AliasChoices("ROUTER_ENABLED", "router_enabled"))
    semantic_router_enabled: bool = Field(True, validation_alias=AliasChoices("SEMANTIC_ROUTER_ENABLED", "semantic_router_enabled"))
    # Experimental only: normal routing does not spend an LLM call.
    llm_router_enabled: bool = Field(False, validation_alias=AliasChoices("LLM_ROUTER_ENABLED", "llm_router_enabled"))
    router_model: str = Field("", validation_alias=AliasChoices("ROUTER_MODEL", "router_model"))
    router_timeout_seconds: float = Field(8, gt=0, le=60, validation_alias=AliasChoices("ROUTER_TIMEOUT", "ROUTER_TIMEOUT_SECONDS"))
    semantic_router_min_confidence: float = Field(0.72, ge=0.5, le=1)
    router_max_characters: int = Field(1200, ge=100, le=12000)
    data_dir: Path = Path("data")

    # LLM Settings
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "your-tool-calling-model"
    subagent_model: str = ""
    llm_thinking: bool = Field(False, validation_alias=AliasChoices("LLM_THINKING", "llm_thinking"))
    llm_timeout_seconds: float = Field(45, gt=0, le=300, validation_alias=AliasChoices("LLM_TIMEOUT", "LLM_TIMEOUT_SECONDS"))
    request_timeout_seconds: float = Field(120, gt=0, le=600, validation_alias=AliasChoices("REQUEST_TIMEOUT", "REQUEST_TIMEOUT_SECONDS"))
    max_active_requests: int = Field(4, ge=1, le=32, validation_alias=AliasChoices("MAX_REQUESTS", "MAX_ACTIVE_REQUESTS"))
    max_parallel_subagents: int = Field(3, ge=1, le=8, validation_alias=AliasChoices("MAX_SUBAGENTS", "MAX_PARALLEL_SUBAGENTS"))
    max_delegated_tasks: int = Field(8, ge=1, le=32, validation_alias=AliasChoices("MAX_TASKS", "MAX_DELEGATED_TASKS"))
    max_agent_steps: int = Field(35, ge=5, le=100)
    deep_timeout_seconds: float = Field(35, gt=0, le=300, validation_alias=AliasChoices("DEEP_TIMEOUT", "DEEP_TIMEOUT_SECONDS"))
    deep_max_agent_steps: int = Field(12, ge=3, le=100, validation_alias=AliasChoices("DEEP_MAX_AGENT_STEPS", "deep_max_agent_steps"))

    # Embedding & RAG Settings
    embedding_provider: Literal["hash", "openai", "huggingface"] = "hash"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr = SecretStr("")
    hf_token: SecretStr = SecretStr("")
    hf_hub_offline: bool = Field(False, validation_alias=AliasChoices("HF_HUB_OFFLINE", "hf_hub_offline"))
    embedding_model: str = "text-embedding-3-small"
    embedding_revision: str = "v1"
    local_embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_device: Literal["auto", "cuda", "cpu"] = "auto"
    embedding_batch_size: int = Field(32, ge=1, le=256)
    embedding_max_length: int = Field(256, ge=32, le=2048)
    chunk_size: int = Field(512, ge=128, le=2048)
    chunk_overlap: int = Field(64, ge=0)
    retrieval_top_k: int = Field(5, ge=1, le=15)
    fast_min_sources: int = Field(1, ge=0, le=15, validation_alias=AliasChoices("FAST_MIN_SOURCES", "fast_min_sources"))
    # Raw hybrid/RRF scores are not calibrated probabilities; keep 0 until evaluated.
    fast_min_retrieval_score: float = Field(0, ge=0, le=1, validation_alias=AliasChoices("FAST_MIN_RETRIEVAL_SCORE", "fast_min_retrieval_score"))
    vector_min_similarity: float = Field(0.35, ge=0, le=1, validation_alias=AliasChoices("MIN_SIMILARITY", "VECTOR_MIN_SIMILARITY"))
    reranker_enabled: bool = Field(False, validation_alias=AliasChoices("RERANKER_ENABLED", "reranker_enabled"))
    reranker_model: str = Field("BAAI/bge-reranker-v2-m3", validation_alias=AliasChoices("RERANKER_MODEL", "reranker_model"))
    reranker_device: Literal["auto", "cuda", "cpu"] = Field("auto", validation_alias=AliasChoices("RERANKER_DEVICE", "reranker_device"))
    reranker_candidate_k: int = Field(15, ge=2, le=50, validation_alias=AliasChoices("RERANKER_CANDIDATE_K", "reranker_candidate_k"))
    reranker_max_length: int = Field(512, ge=64, le=2048, validation_alias=AliasChoices("RERANKER_MAX_LENGTH", "reranker_max_length"))
    reranker_batch_size: int = Field(12, ge=1, le=64, validation_alias=AliasChoices("RERANKER_BATCH_SIZE", "reranker_batch_size"))
    max_corpus_characters: int = Field(10_000_000, ge=10000, validation_alias=AliasChoices("MAX_CORPUS_CHARS", "MAX_CORPUS_CHARACTERS"))
    max_docx_expanded_bytes: int = Field(60_000_000, ge=1024, validation_alias=AliasChoices("MAX_DOCX_BYTES", "MAX_DOCX_EXPANDED_BYTES"))
    max_upload_bytes: int = Field(15_000_000, ge=1024)
    max_documents: int = Field(200, ge=1, le=10000)
    max_history_messages: int = Field(16, ge=2, le=100, validation_alias=AliasChoices("MAX_HISTORY", "MAX_HISTORY_MESSAGES"))
    allow_hash_embedding: bool = Field(False, validation_alias=AliasChoices("ALLOW_HASH", "ALLOW_HASH_EMBEDDING"))
    allow_anonymous_demo: bool = Field(True, validation_alias=AliasChoices("ALLOW_ANONYMOUS", "ALLOW_ANONYMOUS_DEMO"))

    # TTS Settings
    tts_enabled: bool = False
    tts_base_url: str = "https://ai.vnpost.vn/zero-tts"
    tts_api_key: SecretStr = SecretStr("")
    tts_voice: str = "maichi"
    tts_mode: Literal["standard", "openai"] = "standard"
    tts_timeout_seconds: float = Field(90, gt=0, le=300, validation_alias=AliasChoices("TTS_TIMEOUT", "TTS_TIMEOUT_SECONDS"))
    max_parallel_tts: int = Field(2, ge=1, le=8)
    max_tts_characters: int = Field(5000, ge=100, le=20000, validation_alias=AliasChoices("MAX_TTS_CHARS", "MAX_TTS_CHARACTERS"))
    max_audio_bytes: int = Field(25_000_000, ge=1024)
    audio_ttl_seconds: int = Field(3600, ge=60, validation_alias=AliasChoices("AUDIO_TTL", "AUDIO_TTL_SECONDS"))
    api_keys_json: str = "{}"
    # Only administrators holding this separate secret may label a document as evidence.
    trusted_ingest_key: SecretStr = SecretStr("")
    # Public facts may be verified only from this explicit allowlist.
    official_source_domains: str = "vietnampost.vn"

    # Short clean property aliases
    @property
    def request_timeout(self) -> float:
        return self.request_timeout_seconds

    @property
    def router_timeout(self) -> float:
        return self.router_timeout_seconds

    @property
    def llm_timeout(self) -> float:
        return self.llm_timeout_seconds

    @property
    def deep_timeout(self) -> float:
        return self.deep_timeout_seconds

    @property
    def max_requests(self) -> int:
        return self.max_active_requests

    @property
    def max_subagents(self) -> int:
        return self.max_parallel_subagents

    @property
    def max_tasks(self) -> int:
        return self.max_delegated_tasks

    @property
    def max_history(self) -> int:
        return self.max_history_messages

    @property
    def min_similarity(self) -> float:
        return self.vector_min_similarity

    @property
    def max_corpus_chars(self) -> int:
        return self.max_corpus_characters

    @property
    def max_docx_bytes(self) -> int:
        return self.max_docx_expanded_bytes

    @property
    def max_tts_chars(self) -> int:
        return self.max_tts_characters

    @property
    def tts_timeout(self) -> float:
        return self.tts_timeout_seconds

    @property
    def audio_ttl(self) -> int:
        return self.audio_ttl_seconds

    @property
    def allow_anonymous(self) -> bool:
        return self.allow_anonymous_demo

    @property
    def allow_hash(self) -> bool:
        return self.allow_hash_embedding

    @property
    def api_keys(self) -> dict[str, str]:
        return json.loads(self.api_keys_json)
    @property
    def official_domains(self) -> set[str]:
        return {item.strip().lower().lstrip(".") for item in self.official_source_domains.split(",") if item.strip()}


    @model_validator(mode="after")
    def validate_config(self):
        keys = json.loads(self.api_keys_json)
        if not isinstance(keys, dict) or any(
            not isinstance(k, str) or len(k) < 16 or not k.isascii() or not isinstance(v, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", v)
            for k, v in keys.items()
        ):
            raise ValueError("API_KEYS_JSON must map keys of >=16 characters to safe tenant names")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.reranker_candidate_k < self.retrieval_top_k:
            raise ValueError("RERANKER_CANDIDATE_K must be at least RETRIEVAL_TOP_K")
        if (self.embedding_provider == "huggingface"
                and self.local_embedding_model.lower() == "bkai-foundation-models/vietnamese-bi-encoder"
                and self.chunk_size > self.embedding_max_length):
            raise ValueError(
                "CHUNK_SIZE must not exceed EMBEDDING_MAX_LENGTH for vietnamese-bi-encoder"
            )
        if self.demo_mode is False:
            if not keys:
                raise ValueError("Live mode requires API_KEYS_JSON")
            if not self.llm_api_key.get_secret_value() or self.llm_model.startswith("your-"):
                raise ValueError("Live mode requires LLM_API_KEY and a real LLM_MODEL")
            if self.embedding_provider == "hash" and not self.allow_hash:
                raise ValueError("Hash embeddings are demo-only; configure a semantic embedding")
            if self.embedding_provider == "openai" and not self.embedding_api_key.get_secret_value():
                raise ValueError("Configure EMBEDDING_API_KEY (local servers can use a dummy value)")
        for url in (self.llm_base_url, self.embedding_base_url, self.tts_base_url):
            if not url.startswith(("http://", "https://")):
                raise ValueError("API base URLs must use http(s)")
        return self
