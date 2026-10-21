"""Kiểm tra và xác thực các endpoint mô hình Remote (Embedding BGE-M3 và Qwen3-Reranker-8B) của VNPost."""

import json
import time

from app.core.config import Settings
from app.rag import KnowledgeBases, make_embedding
from app.rag.reranker import CrossEncoderReranker


def main():
    settings = Settings()
    report = {
        "embedding_provider": settings.embedding_provider,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_model": settings.embedding_model,
        "reranker_provider": settings.reranker_provider,
        "reranker_base_url": settings.reranker_base_url,
        "reranker_model": settings.reranker_model,
    }

    # 1. Kiểm tra Embedding vLLM BGE-M3
    print("--- 1. Kiểm tra Embedding BGE-M3 ---")
    t0 = time.perf_counter()
    embed = make_embedding(settings)
    sample_text = "Dịch vụ chuyển phát nhanh EMS bưu chính Việt Nam"
    vector = embed.get_text_embedding(sample_text)
    t_embed = (time.perf_counter() - t0) * 1000
    report["embedding_dimensions"] = len(vector)
    report["embedding_latency_ms"] = round(t_embed, 2)
    print(f"Embedding thành công: {len(vector)} dimensions | Thời gian: {t_embed:.2f} ms")

    # 2. Kiểm tra Reranker vLLM Qwen3-Reranker-8B
    print("\n--- 2. Kiểm tra Reranker Qwen3-Reranker-8B ---")
    t0 = time.perf_counter()
    reranker = CrossEncoderReranker(settings)
    candidates = [
        {"excerpt": "Thời tiết hôm nay nắng ráo, nhiệt độ 28 độ C."},
        {"excerpt": "Quy định gửi hàng EMS: bưu gửi tối đa 30kg, hỗ trợ giao tận nơi toàn quốc."},
        {"excerpt": "VNPost là doanh nghiệp bưu chính nhà nước."},
    ]
    query = "Quy định về trọng lượng và phạm vi chuyển phát EMS"
    ranked = reranker.rerank(query, candidates)
    t_rerank = (time.perf_counter() - t0) * 1000
    report["reranker_latency_ms"] = round(t_rerank, 2)
    report["reranker_top_score"] = ranked[0]["reranker_score"]
    report["reranker_top_excerpt"] = ranked[0]["excerpt"]
    print(f"Reranker thành công: Top 1 score = {ranked[0]['reranker_score']} | Thời gian: {t_rerank:.2f} ms")
    print(f"Top 1 excerpt: {ranked[0]['excerpt']}")

    # 3. Kiểm tra Truy xuất RAG thực tế trên Tenant vnpost
    print("\n--- 3. Kiểm tra Truy xuất RAG trên Kho tri thức VNPost ---")
    t0 = time.perf_counter()
    kb = KnowledgeBases(settings).for_tenant("vnpost")
    rag_query = "Thời gian chuyển phát bưu gửi EMS trong nước"
    hits = kb.retrieve(rag_query, top_k=3)
    t_rag = (time.perf_counter() - t0) * 1000
    report["rag_retrieval_hits"] = len(hits)
    report["rag_latency_ms"] = round(t_rag, 2)
    if hits:
        report["rag_top_doc"] = hits[0]["filename"]
        report["rag_top_reranker_score"] = hits[0].get("reranker_score")
        report["rag_top_rrf_score"] = hits[0].get("retrieval_score")
    print(f"RAG Retrieve thành công: {len(hits)} kết quả | Thời gian: {t_rag:.2f} ms")
    for i, hit in enumerate(hits, 1):
        print(f"  [{i}] {hit['filename']} (Reranker: {hit.get('reranker_score')}, RRF: {hit.get('retrieval_score')})")

    print("\n--- Báo cáo Tổng hợp JSON ---")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
