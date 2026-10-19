"""Đồng bộ toàn bộ dữ liệu tri thức VNPost vào cơ sở dữ liệu Vector Qdrant nội bộ (On-disk)."""

import time
import uuid
from pathlib import Path

from llama_index.core.schema import MetadataMode
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import Settings
from app.rag import KnowledgeBases, make_embedding


def sync_vnpost_to_qdrant(qdrant_path: str = "./data/qdrant_db", collection_name: str = "vnpost_kb", tenant: str = "vnpost"):
    settings = Settings()
    print(f"--- 1. Nạp kho tri thức tenant '{tenant}' ---")
    kb = KnowledgeBases(settings).for_tenant(tenant)
    snapshot = kb.snapshot
    total_nodes = len(snapshot.nodes)
    print(f"Tổng số chunks cần đồng bộ: {total_nodes}")

    vs = snapshot.index.vector_store
    embedding_dict = getattr(vs, "_data", None).embedding_dict if hasattr(vs, "_data") else {}

    print(f"\n--- 2. Khởi tạo Qdrant nội bộ tại '{qdrant_path}' ---")
    db_path = Path(qdrant_path).resolve()
    db_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(db_path))

    # Tái tạo hoặc tạo collection với 1024 dimensions (BGE-M3)
    collections = [col.name for col in client.get_collections().collections]
    if collection_name in collections:
        print(f"Collection '{collection_name}' đã tồn tại -> Làm mới dữ liệu...")
        client.delete_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )
    print(f"Đã tạo collection '{collection_name}' (1024 dims, Cosine metric)")

    # 3. Chuyển đổi và Upsert toàn bộ Chunks
    print("\n--- 3. Chuẩn bị points và nạp vào Qdrant ---")
    t0 = time.perf_counter()
    points = []
    embed_model = None

    for i, node in enumerate(snapshot.nodes):
        node_id = node.node_id
        vector = embedding_dict.get(node_id)
        if not vector:
            if embed_model is None:
                embed_model = make_embedding(settings)
            vector = embed_model.get_text_embedding(node.get_content(metadata_mode=MetadataMode.NONE))

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant}_{node_id}"))
        payload = {
            "node_id": node_id,
            "document_id": str(node.metadata.get("document_id", "")),
            "filename": str(node.metadata.get("filename", "")),
            "location": str(node.metadata.get("location", "")),
            "text": node.get_content(metadata_mode=MetadataMode.NONE),
            "is_global": node.metadata.get("is_global") in (True, "true"),
            "session_id": str(node.metadata.get("session_id") or ""),
            "user_id": str(node.metadata.get("user_id") or ""),
            "authority": str(node.metadata.get("authority", "official_public")),
            "source_url": str(node.metadata.get("source_url") or ""),
            "issuer": str(node.metadata.get("issuer") or ""),
            "tenant": tenant,
        }
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    # Batch upsert 200 points / lần
    batch_size = 200
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        client.upsert(collection_name=collection_name, points=batch, wait=True)
        print(f"Đã nạp {min(start + batch_size, len(points))}/{len(points)} chunks...")

    elapsed = time.perf_counter() - t0
    info = client.get_collection(collection_name)
    print(f"\n=> ĐỒNG BỘ THÀNH CÔNG sau {elapsed:.2f} giây!")
    print(f"Số lượng vector đã index trong Qdrant: {info.points_count}")

    # 4. Kiểm tra tìm kiếm thực tế trên Qdrant
    print("\n--- 4. Kiểm tra tìm kiếm Semantic trực tiếp trên Qdrant ---")
    test_query = "Thời gian và quy định chuyển phát nhanh EMS"
    embed_model = make_embedding(settings)
    q_vec = embed_model.get_query_embedding(test_query)

    search_res = client.query_points(
        collection_name=collection_name,
        query=q_vec,
        limit=3,
    ).points

    print(f"Query: '{test_query}'")
    for idx, hit in enumerate(search_res, 1):
        print(f"  [{idx}] Score: {hit.score:.4f} | File: {hit.payload.get('filename')} | Location: {hit.payload.get('location')}")
        snippet = hit.payload.get('text', '').replace('\n', ' ')[:100]
        print(f"       Snippet: {snippet}...")

    client.close()
    print("\nĐã đóng kết nối Qdrant an toàn.")


if __name__ == "__main__":
    sync_vnpost_to_qdrant()
