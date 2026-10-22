"""Reranking service for the final RAG candidate set.

Dense/BM25 retrieval is optimized for recall: it finds a small candidate pool.
The reranker evaluates the query and candidate passages together via the
VNPost vLLM REST API (Qwen3-Reranker-8B) to rank and order that pool before
passing evidence to the LLM.
"""

import logging

import httpx

from app.core.config import Settings
from app.core.providers import ProviderClients

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Reranker using remote REST API (e.g. VNPost vLLM Qwen3-Reranker-8B)."""

    def __init__(self, settings: Settings, clients: ProviderClients | None = None):
        self.settings = settings
        self.clients = clients
        self.provider = settings.reranker_provider

    def _rerank_api(self, query: str, candidates: list[dict]) -> list[dict]:
        url = self.settings.reranker_base_url
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.reranker_api_key.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        docs = [str(candidate["excerpt"]) for candidate in candidates]
        payload = {
            "query": query,
            "documents": docs,
        }

        client = self.clients.sync if self.clients else None
        try:
            if client:
                resp = client.post(url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as c:
                    resp = c.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            scores = {
                item["index"]: float(item["relevance_score"])
                for item in results
                if "index" in item and "relevance_score" in item
            }
            ranked = []
            for idx, candidate in enumerate(candidates):
                score = scores.get(idx, 0.0)
                ranked.append({**candidate, "reranker_score": round(score, 6)})
            return sorted(ranked, key=lambda item: item["reranker_score"], reverse=True)
        except Exception as exc:
            logger.warning(
                "Remote rerank API call failed (%s): %s; retaining original order", url, exc
            )
            return candidates

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Return candidates in reranker order, retaining original metadata."""
        if len(candidates) < 2:
            return candidates
        if self.provider == "api":
            return self._rerank_api(query, candidates)
        logger.warning(
            "Reranker provider '%s' is not supported; remote 'api' is required.", self.provider
        )
        return candidates
