# Báo Cáo Đo Đạc Hiệu Năng & Đánh Giá Năng Lực Hệ Thống (Mipo VNPost Reports)

> **Cập nhật ngày:** 21/10/2026  
> **Phiên bản hệ thống:** v1.2.0 (Kiến trúc Modular Subagents, FastMCP Server, Giao thức A2A SDK & 197/197 Tests Passed)  
> **Môi trường đo đạc:** Python 3.12, PyTorch 2.6.0, Sentence-Transformers, LlamaIndex, PostgreSQL / SQLite Checkpointer

---

## 1. Tổng quan thư mục `reports/`

Thư mục `reports/` chứa kết quả đo đạc thực nghiệm toàn diện về độ trễ, lưu lượng token, tỷ lệ định tuyến Zero-LLM, độ chính xác của 7 tác tử con (Subagents), và năng lực xử lý đồng thời (parallel subagents) của trợ lý ảo bưu chính MiPo VNPost:

| Tên tệp tin | Định dạng | Mục đích & Ý nghĩa | Chế độ đo |
| :--- | :---: | :--- | :---: |
| **`architecture_metrics.json`** | JSON | Báo cáo chi tiết định tuyến 4 tầng (Tier 0, 1, 2, 3), kiểm tra Source Gate, TTFT và độ trễ phản hồi | Demo / Live |
| **`architecture_comparison.json`** | JSON | Đối sánh đa chiều giữa 3 cơ chế thực thi: `auto` (thích ứng), `fast` (cưỡng bức Fast RAG) và `deep` (cưỡng bức Deep Agent) | Demo / Live |
| **`parallel_subagents_demo.json`** | JSON | Đo đạc hiệu năng thực thi song song của Supervisor với các tác tử con, kiểm chứng giới hạn Semaphore slot (`max_parallel_subagents = 3`) | Demo Deterministic |
| **`parallel_subagents_live.json`** | JSON | Kết quả đo đạc thực thi song song trên endpoint LLM thực tế (`gemini-2.5-flash`) | Live API |
| **`parallel_subagents_live_forced.json`** | JSON | Đo đạc tác vụ phức tạp cưỡng bức chế độ Deep Agent với luồng hội thoại đa chặng thực tế | Live API Forced Deep |
| **`subagents_benchmark.json`** | JSON | Báo cáo đánh giá năng lực tự động của toàn bộ 7 Tác tử con độc lập (`eval_runner.py`), đo tỷ lệ chính xác và thời gian thực thi | Độc lập (100% Pass) |
| **`architecture_benchmark_live.stdout.log`** | LOG | Nhật ký luồng chuẩn (stdout) của phiên chạy benchmark trực tiếp | Live |
| **`architecture_benchmark_live.stderr.log`** | LOG | Nhật ký tải trọng số mô hình nhúng cục bộ (`vietnamese-bi-encoder`) | Live |

---

## 2. Kết quả Đo đạc Định tuyến & Độ trễ (Architecture Metrics)

Đo đạc trên bộ dữ liệu `evaluation/architecture_benchmark.jsonl`:

- **Tổng số mẫu:** 8/8 truy vấn mẫu (đại diện cho mọi tình huống: Chào hỏi, Tra cứu dịch vụ, Quy định hải quan, Soạn tóm tắt, Lý do hạn chế, So sánh đa chiều, Tính toán cước bưu kiện, Hỏi đáp phức hợp).
- **Tỷ lệ hoàn thành:** **100% (8/8)**, 0 lỗi, 0 sự cố timeout.
- **Phân bổ tuyến thực thi (Route Distribution):**
  - **Local (Tier 0 Fastpath):** 1 mẫu (Chào hỏi) — Độ trễ: **47 ms**, TTFT: **15 ms**, tiêu tốn **0 token LLM**, 0 cuộc gọi RAG.
  - **Calculator (Tier 0 AST):** 1 mẫu (Tính toán) — Độ trễ: **46 ms**, TTFT: **31 ms**, bảo mật AST sandbox không dùng LLM.
  - **Fast (Tier 1 Fast RAG):** 3 mẫu — Độ trễ P50: **343 ms**, Source Gate đạt chuẩn 100% nguồn bưu chính.
  - **Deep (Tier 2/3 Deep Agent):** 3 mẫu — Phân rã đa tác tử, điều phối song song.
- **Thời gian nhận token đầu tiên (Overall P50 TTFT):** **312 ms**.
- **Độ trễ trung vị toàn hệ thống (Overall P50 Latency):** **343 ms**.

---

## 3. Đối sánh 3 Cơ chế Định tuyến (`architecture_comparison.json`)

| Tiêu chí | Chế độ `auto` (Khuyến nghị) | Chế độ `fast` (Chỉ RAG) | Chế độ `deep` (Đa tác tử) |
| :--- | :---: | :---: | :---: |
| **Độ trễ trung vị (P50)** | **328 ms** | **234 ms** | **375 ms** |
| **Độ trễ phân vị cao (P95)** | 23.250 ms | 18.750 ms | 20.906 ms |
| **Thời gian ra token đầu (P50 TTFT)** | **313 ms** | **203 ms** | **344 ms** |
| **Số lượt gọi LLM trung bình** | 2.25 lượt | 0.75 lượt | 3.75 lượt |
| **Số lượt truy xuất tài liệu (RAG)** | 0.75 lượt | 0.75 lượt | 0.75 lượt |
| **Tỷ lệ trúng bộ nhớ đệm (Cache Hit)** | **0.38** | 0.00 | **0.75** |
| **Số tác vụ ủy quyền cho Subagent** | 0.75 tác vụ | 0.00 tác vụ | 1.50 tác vụ |
| **Đánh giá nghiệp vụ** | **Tối ưu nhất:** Tiết kiệm tài nguyên cho câu đơn giản, mở rộng đầy đủ công cụ cho tác vụ phức tạp | Tốc độ nhanh nhất nhưng không hỗ trợ tạo đơn HITL hay tính toán nâng cao | Toàn diện nhất nhưng tốn nhiều chi phí token nếu áp dụng cho cả chào hỏi |

---

## 4. Báo cáo Năng lực 7 Tác tử Con (`subagents_benchmark.json`)

Toàn bộ 7 tác tử con được thiết kế module hóa trong `app/agents/subagents/` đã trải qua bài kiểm tra đánh giá năng lực nghiệp vụ tự động:

- **Tổng số Tác tử:** 7 tác tử
- **Tác tử đạt chuẩn:** **7/7 (100%)**
- **Trạng thái Sức khỏe Hệ thống:** **`healthy`**

| Tác tử (Subagent) | Nhiệm vụ chính | Mẫu thử | Độ chính xác | Thời gian thực thi | Trạng thái |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **`tracking-agent`** | Tra cứu bưu phẩm UPU S10, bóc tách tiến trình phát | 3/3 | **100.0%** | 0.0001 s | ✅ ĐẠT |
| **`booking-agent`** | Tạo đơn hàng nháp, tính cước bưu kiện chia 6000 | 2/2 | **100.0%** | 0.0000 s | ✅ ĐẠT |
| **`complaint-agent`** | Tiếp nhận khiếu nại, đối soát thời hiệu 6/12 tháng | 1/1 | **100.0%** | 0.0000 s | ✅ ĐẠT |
| **`analyst-agent`** | Phân tích quy chuẩn thể tích, tính ngày tháng UTC+7 | 1/1 | **100.0%** | 0.0000 s | ✅ ĐẠT |
| **`post-office-agent`** | Tra cứu bưu cục VNPost theo mã Vpostcode & GPS | 1/1 | **100.0%** | 0.0000 s | ✅ ĐẠT |
| **`rag-agent`** | Truy xuất điều lệ bưu chính chuyên sâu LlamaIndex | 1/1 | **100.0%** | 0.0002 s | ✅ ĐẠT |
| **`writer-agent`** | Soạn thảo phản hồi hành chính theo cơ chế Fork state | 1/1 | **100.0%** | 0.0000 s | ✅ ĐẠT |

---

## 5. Hướng dẫn Tái hiện & Chạy Lại Đo đạc (Reproduction Steps)

### A. Đo đạc định tuyến và độ trễ cơ bản
```powershell
# Chạy ở chế độ mô phỏng kiểm thử nhanh (Demo Deterministic):
.\.venv\Scripts\python scripts\benchmark_architecture.py

# Chạy với endpoint API LLM thực tế cấu hình trong .env:
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live
```

### B. Chạy đối sánh đa chế độ (Auto vs Fast vs Deep)
```powershell
.\.venv\Scripts\python scripts\compare_architectures.py --tenant vnpost
```

### C. Đo đạc năng lực xử lý song song (Parallel Subagents)
```powershell
.\.venv\Scripts\python scripts\benchmark_architecture.py --dataset evaluation\parallel_subagents_benchmark.jsonl --output reports\parallel_subagents_demo.json
```

### D. Chạy đánh giá tự động Benchmark 7 Subagent độc lập
```powershell
.\.venv\Scripts\python -m app.agents.eval_runner
```
Kết quả sẽ tự động được cập nhật và lưu trữ trực tiếp vào [reports/subagents_benchmark.json](file:///c:/Users/admin/Downloads/vnpost_deepagent/reports/subagents_benchmark.json).
