"""GPU-capable embedding adapter for BKAI's Vietnamese bi-encoder.

The model card requires Vietnamese word segmentation before encoding.  Keeping that
preprocessing inside the embedding adapter guarantees that document and query vectors
use exactly the same representation.
"""

import asyncio
import threading
from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr


class VietnameseBiEncoderEmbedding(BaseEmbedding):
    """SentenceTransformers adapter for ``bkai-foundation-models/vietnamese-bi-encoder``."""

    model_name: str
    device: str = "cpu"
    max_length: int = 256
    _encoder: Any = PrivateAttr()
    _tokenize: Any = PrivateAttr()
    _encode_lock: Any = PrivateAttr(default_factory=threading.Lock)

    def __init__(self, **data: Any):
        super().__init__(**data)
        try:
            import importlib
            pyvi = importlib.import_module("pyvi")
            ViTokenizer = pyvi.ViTokenizer
            st = importlib.import_module("sentence_transformers")
            SentenceTransformer = st.SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Vietnamese local embedding requires the 'local-embedding' optional dependency. "
                "Create the Conda environment from environment.yml."
            ) from exc
        self._tokenize = ViTokenizer.tokenize
        actual_device = self.device
        if actual_device == "auto":
            try:
                import importlib
                torch = importlib.import_module("torch")
                actual_device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                actual_device = "cpu"
        self._encoder = SentenceTransformer(self.model_name, device=actual_device)
        # The model card declares a maximum sequence length of 256 tokens.  Explicitly
        # set it so a package default cannot silently truncate at another length.
        self._encoder.max_seq_length = self.max_length

    def _prepare(self, text: str) -> str:
        return self._tokenize(text.strip()) if text and text.strip() else ""

    def _encode(self, texts: list[str]) -> list[list[float]]:
        with self._encode_lock:
            vectors = self._encoder.encode(
                [self._prepare(text) for text in texts],
                batch_size=self.embed_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return vectors.tolist()

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._encode([query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await asyncio.to_thread(self._encode, [query]))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._encode([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)
