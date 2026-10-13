"""Verify the CUDA embedding path without printing configuration secrets."""

import json

import torch

from app.config import Settings
from app.rag import make_embedding, resolve_embedding_device
from app.reranker import CrossEncoderReranker


def main():
    settings = Settings()
    device = resolve_embedding_device(settings.embedding_device)
    report = {
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "device": device,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.local_embedding_model,
    }
    embedding = make_embedding(settings)
    vector = embedding.get_query_embedding("Kiểm tra truy xuất bưu gửi tại Hà Nội")
    report["embedding_dimensions"] = len(vector)
    report["embedding_norm"] = round(sum(value * value for value in vector) ** 0.5, 6)
    if settings.reranker_enabled:
        reranker = CrossEncoderReranker(settings)
        ranked = reranker.rerank("Thời hạn hoàn cước", [
            {"excerpt": "Thời hạn hoàn cước là 7 ngày."},
            {"excerpt": "Bưu cục làm việc vào thứ bảy."},
        ])
        report["reranker_model"] = settings.reranker_model
        report["reranker_device"] = reranker.device
        report["reranker_candidates"] = len(ranked)
        report["reranker_top_excerpt"] = ranked[0]["excerpt"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if device != "cuda" or not report["cuda_available"]:
        raise SystemExit("Embedding is not running on CUDA.")
    if report["embedding_dimensions"] != 768:
        raise SystemExit("Unexpected Vietnamese bi-encoder embedding dimension.")
    if settings.reranker_enabled and report["reranker_top_excerpt"] != "Thời hạn hoàn cước là 7 ngày.":
        raise SystemExit("Reranker sanity check did not rank the relevant passage first.")


if __name__ == "__main__":
    main()
