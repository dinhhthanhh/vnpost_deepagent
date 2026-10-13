"""Local cross-encoder reranking for the final RAG candidate set.

Dense/BM25 retrieval is optimized for recall: it finds a small pool that is
likely to contain the right passage.  A cross-encoder sees the question and a
candidate passage together, so it is used only to order that pool before it is
shown to the LLM.
"""

import logging
import threading
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


def resolve_reranker_device(requested: str) -> str:
    """Resolve a requested GPU explicitly; never silently fall back from CUDA."""
    try:
        import torch
    except ImportError as exc:
        if requested == "cuda":
            raise RuntimeError("RERANKER_DEVICE=cuda requires the PyTorch CUDA build.") from exc
        return "cpu"
    available = torch.cuda.is_available()
    if requested == "auto":
        return "cuda" if available else "cpu"
    if requested == "cuda" and not available:
        raise RuntimeError("RERANKER_DEVICE=cuda was requested but PyTorch cannot see an NVIDIA GPU.")
    return requested


class CrossEncoderReranker:
    """Thread-safe, lazy BGE cross-encoder wrapper.

    Model loading is delayed until the first retrieval so an API process can
    start without a model download.  Production setup should run
    ``scripts/verify_gpu.py`` first, which warms this model and catches model
    download/CUDA errors before traffic is accepted.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.device = resolve_reranker_device(settings.reranker_device)
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        # Transformer GPU inference is not safely parallel across arbitrary
        # worker threads.  Batch within one call and serialize model access.
        self._predict_lock = threading.Lock()

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "Local reranking requires sentence-transformers. "
                    "Create the Conda environment from environment.yml."
                ) from exc
            model = CrossEncoder(
                self.settings.reranker_model,
                max_length=self.settings.reranker_max_length,
                device=self.device,
            )
            if self.device == "cuda":
                # The RTX 4060 Ti has ample VRAM for the candidate batch.  FP16
                # substantially lowers memory/latency and does not alter source
                # provenance; ranking quality must still be measured on VNPost data.
                model.model.half()
            self._model = model
            logger.info("reranker_loaded model=%s device=%s", self.settings.reranker_model, self.device)
            return model

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Return candidates in cross-encoder order, retaining original metadata."""
        if len(candidates) < 2:
            return candidates
        model = self._get_model()
        pairs = [(query, str(candidate["excerpt"])) for candidate in candidates]
        with self._predict_lock:
            scores = model.predict(
                pairs,
                batch_size=self.settings.reranker_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        ranked = []
        for candidate, score in zip(candidates, scores, strict=True):
            # Cross-encoder logits are useful for trace/debugging, but they are
            # not calibrated probabilities and are deliberately not exposed as
            # a claim about answer correctness.
            ranked.append({**candidate, "reranker_score": round(float(score), 6)})
        return sorted(ranked, key=lambda item: item["reranker_score"], reverse=True)
