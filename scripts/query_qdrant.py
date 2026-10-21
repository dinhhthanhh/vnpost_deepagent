"""Truy vấn tìm kiếm ngữ nghĩa và lọc siêu dữ liệu trực tiếp trên Qdrant nội bộ."""

import argparse
import time

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.core.config import Settings
from app.rag import make_embedding
from app.rag.reranker import CrossEncoderReranker


def query_qdrant(
    query_text: str,
    top_k: int = 5,
    qdrant_path: str = "./data/qdrant_db",
    collection_name: str = "vnpost_kb",
    use_reranker: bool = True,
    filename_filter: str | None = None,
):
    settings = Settings()
    print("--- 1. Mã hóa câu hỏi bằng BGE-M3 (1024d) ---")
    embed_model = make_embedding(settings)
    t0 = time.perf_counter()
    query_vector = embed_model.get_query_embedding(query_text)
    t_embed = (time.perf_counter() - t0) * 1000
    print(f"Đã tạo vector trong {t_embed:.2f} ms")

    print(f"\n--- 2. Truy vấn Vector Search trên Qdrant ({qdrant_path}) ---")
    client = QdrantClient(path=qdrant_path)

    query_filter = None
    if filename_filter:
        query_filter = Filter(
            must=[FieldCondition(key="filename", match=MatchValue(value=filename_filter))]
        )

    t0 = time.perf_counter()
    # Tìm kiếm candidate (lấy dư nếu có reranker)
    candidate_limit = top_k * 3 if use_reranker else top_k
    search_res = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        limit=candidate_limit,
    ).points
    t_search = (time.perf_counter() - t0) * 1000
    print(f"Tìm thấy {len(search_res)} candidates trong {t_search:.2f} ms")

    candidates = []
    for hit in search_res:
        candidates.append({
            "chunk_id": hit.id,
            "score": round(hit.score, 4),
            "filename": hit.payload.get("filename"),
            "location": hit.payload.get("location"),
            "excerpt": hit.payload.get("text"),
            "authority": hit.payload.get("authority"),
        })

    # 3. Tái xếp hạng (nếu bật Reranker)
    final_results = candidates
    if use_reranker and candidates:
        print("\n--- 3. Tái xếp hạng qua Qwen3-Reranker-8B API ---")
        t0 = time.perf_counter()
        reranker = CrossEncoderReranker(settings)
        final_results = reranker.rerank(query_text, candidates)
        t_rerank = (time.perf_counter() - t0) * 1000
        print(f"Rerank hoàn tất trong {t_rerank:.2f} ms")

    client.close()

    print(f"\n=== KẾT QUẢ TOP {top_k} CHO: '{query_text}' ===")
    for idx, item in enumerate(final_results[:top_k], 1):
        rerank_score = item.get("reranker_score")
        score_str = f"Reranker: {rerank_score:.4f} | Cosine: {item.get('score')}" if rerank_score is not None else f"Cosine: {item.get('score')}"
        print(f"[{idx}] {item.get('filename')} ({score_str})")
        print(f"     Vị trí: {item.get('location')}")
        snippet = str(item.get("excerpt", "")).replace("\n", " ")[:140]
        print(f"     Nội dung: {snippet}...\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query local Qdrant vector database")
    parser.add_argument("--query", "-q", default="Bưu điện bồi thường như thế nào khi bưu gửi bị mất?")
    parser.add_argument("--top_k", "-k", type=int, default=3)
    parser.add_argument("--no-rerank", action="store_true", help="Bỏ qua bước rerank")
    parser.add_argument("--filter-file", default=None, help="Lọc theo tên file chính xác")
    args = parser.parse_args()

    query_qdrant(
        query_text=args.query,
        top_k=args.top_k,
        use_reranker=not args.no_rerank,
        filename_filter=args.filter_file,
    )
