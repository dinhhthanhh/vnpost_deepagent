# Chatbot Deep Agent VNPost

Bộ mã nguồn chạy từ thư mục này, gồm backend FastAPI, Deep Agents điều phối sub-agent, RAG DOCX/TXT bằng LlamaIndex và giọng đọc ZeroTTS. Router hai tầng giữ các câu tra cứu rõ ràng ở đường nhanh, còn câu mơ hồ được LLM phân loại ý định trước khi chọn Deep Agent. Giao diện React đã được build sẵn trong bản ZIP, nên lần chạy đầu không cần Node.js.

**Bắt đầu bằng demo; chuyển sang LLM và embedding thật khi đã điền cấu hình.** Demo dùng chính thư viện Deep Agents/LlamaIndex với model kịch bản và embedding hash, để thử luồng chạy, giao nhiệm vụ và nguồn. Demo không phản ánh chất lượng suy luận của LLM thật. Dữ liệu trong `examples/` là giả lập.

## Chạy nhanh trên Windows với Conda và GPU (khuyến nghị)

Máy này có RTX 4060 Ti 16 GB. Cấu hình mặc định dùng CUDA cho embedding cục bộ
`bkai-foundation-models/vietnamese-bi-encoder`; LLM vẫn chạy qua API nội bộ. Conda đã
có tại `%USERPROFILE%\\miniconda3` dù chưa được thêm vào `PATH`.

```powershell
.\scripts\setup-conda.ps1
C:\Users\Admin\miniconda3\condabin\conda.bat run -n vnpost-deepagent python scripts\verify_gpu.py
C:\Users\Admin\miniconda3\condabin\conda.bat run -n vnpost-deepagent python scripts\check_services.py --live
C:\Users\Admin\miniconda3\condabin\conda.bat run -n vnpost-deepagent python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-proxy-headers
```

`.env` cục bộ đã được tạo, chứa URL/model LLM và khóa do bạn cung cấp; file này bị Git
bỏ qua. Lần chạy đầu sẽ tải model embedding từ Hugging Face. Với model BKAI, văn bản
được word-segment bằng PyVi trước khi embedding (yêu cầu của model card), vector có 768
chiều, và chunk được đặt 220/32 để không vượt giới hạn 256 token của model.

`scripts/check_services.py --live` là kiểm tra bắt buộc trước khi chạy Deep Agent: nó
xác minh tool calling, vì chat văn bản đơn thuần không đủ cho `create_deep_agent`.

RAG mặc định kết hợp BM25 và vector BKAI rồi dùng cross-encoder
`BAAI/bge-reranker-v2-m3` trên GPU để xếp lại tối đa 15 đoạn ứng viên trước khi đưa
5 nguồn tốt nhất vào LLM. Lần đầu chạy `verify_gpu.py` sẽ tải reranker; chỉ khởi động
API sau khi script xác nhận passage liên quan được xếp đầu.

## Chạy bằng virtualenv (CPU/demo)

Cần Python 3.12. Mở PowerShell tại thư mục đã giải nén:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\seed_demo.py
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-proxy-headers
```

Mở [http://127.0.0.1:8080](http://127.0.0.1:8080). Hỏi “Thời hạn hoàn cước trong tài liệu mẫu là bao nhiêu ngày?”. Mở phần nguồn để đối chiếu. Hoặc tải lên DOCX/TXT của bạn và đặt câu hỏi tương ứng. Với phép tính thuần túy như `120 - 100`, bỏ chọn “Yêu cầu trích nguồn tài liệu”.

Những lần sau có thể chạy `start.ps1`, hoặc dùng lại câu lệnh Uvicorn. Không cần kích hoạt virtualenv hay thay đổi execution policy nếu dùng các câu lệnh đầy đủ ở trên. `seed_demo.py` chỉ nạp dữ liệu giả lập khi `DEMO_MODE=true`.

## Linux và macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python scripts/seed_demo.py
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-proxy-headers
```

## Chuyển sang API thật

Dừng máy chủ, sửa `.env`:

```dotenv
DEMO_MODE=false
DATA_DIR=./data-live
LLM_BASE_URL=https://YOUR-LLM-HOST/v1
LLM_API_KEY=YOUR-KEY
LLM_MODEL=YOUR-TOOL-CALLING-MODEL-ID
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://YOUR-EMBEDDING-HOST/v1
EMBEDDING_API_KEY=YOUR-KEY
EMBEDDING_MODEL=YOUR-EMBEDDING-MODEL-ID
API_KEYS_JSON={"REPLACE-WITH-A-LONG-RANDOM-SECRET":"vnpost"}
TTS_ENABLED=true
TTS_BASE_URL=https://ai.vnpost.vn/zero-tts
TTS_VOICE=maichi
TTS_MODE=standard
```

`LLM_BASE_URL` và `EMBEDDING_BASE_URL` phải có đường dẫn `/v1` đúng theo máy chủ của bạn. LLM cần hỗ trợ **tool/function calling**; khả năng chat text thông thường chưa đủ. Với máy chủ nội bộ không kiểm tra khóa, điền chuỗi dummy vào biến khóa để SDK khởi tạo được. `SUBAGENT_MODEL` cho phép dùng model khác cho các chuyên viên; để trống thì dùng cùng model chính.

Khởi động lại, nhập khóa chatbot vào phần “Khóa truy cập” của giao diện, rồi tải tài liệu thật lên. Khóa chatbot (`API_KEYS_JSON`) dùng giữa giao diện và backend; khóa LLM/embedding/TTS chỉ nằm trên máy chủ. Mỗi khóa được ánh xạ tới một tenant. Những người cùng tenant chia sẻ kho tài liệu và có quyền xem hội thoại của tenant đó.

Kiểm tra các dịch vụ bằng một câu thử ngắn, không gửi tài liệu trong KB:

```powershell
.venv\Scripts\python.exe scripts\check_services.py --live --tts
```

Lệnh này gọi API thật và có thể dùng quota. TTS có thể không cần khóa; nếu hệ thống yêu cầu Bearer token, cấu hình `TTS_API_KEY`.

Không dùng lại index hash của demo cho model thật. Dùng `DATA_DIR` riêng như ví dụ, hoặc dừng máy chủ và chạy `scripts/reindex.py --tenant TENANT` sau khi đổi embedding. Khi trọng số của một model trên server đổi nhưng tên model giữ nguyên, tăng `EMBEDDING_REVISION` trước khi reindex để tránh tái sử dụng vector cũ.

## Embedding chạy cục bộ

```powershell
.venv\Scripts\python.exe -m pip install -e ".[local-embedding]"
```

Đặt `EMBEDDING_PROVIDER=huggingface` và `LOCAL_EMBEDDING_MODEL` trong `.env`. Mặc định sử dụng `intfloat/multilingual-e5-small` với tiền tố `query:`/`passage:`. Lần đầu cần tải model hoặc trỏ tới thư mục model đã có. Đây là một cấu hình khởi điểm; chọn model cuối cùng theo bộ câu hỏi tiếng Việt của đơn vị.

## Giao diện và âm thanh

Giao diện có upload/xóa tài liệu, lịch sử theo phiên, xem nguồn, hủy yêu cầu, danh sách giọng, đọc WAV đầy đủ, streaming WAV và tải file âm thanh. Chat nhận tiến trình qua SSE; **câu trả lời chữ đã kiểm tra nguồn được gửi trước khi chờ TTS**. SSE hiện truyền tiến trình và câu trả lời hoàn chỉnh, không truyền từng token chưa kiểm tra.

Ở chế độ có nguồn, backend chặn mã `[S...]` không tồn tại và không trả lời một nội dung tài liệu khi thiếu nguồn. Việc một nguồn tồn tại chưa chứng minh mọi câu trong đáp án đều được nguồn hỗ trợ; cần kiểm thử bằng dữ liệu nghiệp vụ thật.

Streaming đọc cấu trúc RIFF/WAV theo chunk, giữ byte chưa đủ, nhận tần số thực từ `fmt`, và đo thời gian nhận PCM. Không cố định header 44 byte. WAV streaming cần PCM 16-bit mono/stereo. Trình duyệt có thể yêu cầu bấm Nghe vì chính sách autoplay. TTS là **đầu ra giọng nói**; bản này không bao gồm nhận dạng tiếng nói đầu vào.

## Phát triển frontend

```bash
cd frontend
npm ci
npm run dev
```

Vite chạy tại `http://127.0.0.1:5173`, proxy `/api` sang backend cổng 8080. Sau khi sửa, chạy `npm run build` rồi khởi động lại backend để dùng bản build mới. Frontend cùng origin với backend, nên không cần mở CORS tùy ý.

## Docker

Sao chép `.env.example` thành `.env`, đặt một khóa ngẫu nhiên trong `API_KEYS_JSON`, rồi chạy:

```bash
docker compose up --build -d
```

Container có thể nhìn thấy client qua địa chỉ gateway Docker, nên cần nhập khóa ngay cả khi mở từ localhost. Cổng mặc định chỉ bind localhost. Dữ liệu được lưu trong volume `chatbot_data`. Image chạy dưới user không phải root. Đây là cấu hình một instance với `--workers 1`.

## Kiểm thử và đánh giá

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check app scripts tests
cd frontend
npm run test
npm run build
```

`docs/VALIDATION.md` mô tả phạm vi các kiểm tra đã thực hiện. Test contract chạy SDK LLM/embedding thật nhưng mock HTTP; không có test nào dùng khóa hay gọi máy chủ VNPost thật.

Để đo retrieval, tạo JSONL theo `evaluation/questions.jsonl.example`, gán đáp án và đoạn nguồn đúng, rồi chạy:

```powershell
.venv\Scripts\python.exe scripts\evaluate_retrieval.py --tenant vnpost --dataset questions.jsonl --output retrieval_report.json
```

Báo cáo gồm Recall@K, MRR@K, kết quả câu không có đáp án và p50/p95 retrieval. Những chỉ số này không thay thế đánh giá tính đúng của câu trả lời cuối cùng. Hướng dẫn xây bộ đánh giá và chọn cấu hình nằm trong `docs/ARCHITECTURE.md`.

## Cấu trúc mã nguồn

| Tệp | Trách nhiệm |
|---|---|
| `app/agents.py` | Deep Agent, registry sub-agent, `task`, `parallel_tasks`, kiểm tra nguồn |
| `app/rag.py` | DOCX/TXT, LlamaIndex, vector + BM25, RRF, snapshot index |
| `app/embedding_cache.py` | Cache vector bền vững, tách truy vấn và đoạn tài liệu |
| `app/prompts.py` | Vai trò và nguyên tắc bằng chứng của từng agent |
| `app/service.py` | Timeout, quản lý phiên, gửi chữ trước âm thanh |
| `app/tts.py` | Adapter ZeroTTS theo Postman |
| `app/main.py` | API, xác thực tenant, SSE, phục vụ React |
| `app/store.py` | SQLite lưu hội thoại, nguồn và âm thanh |
| `frontend/src/wav-stream.js` | Parser WAV streaming không phụ thuộc ranh giới chunk |
| `docs/ARCHITECTURE.md` | Kiến trúc, luồng chạy, lựa chọn kỹ thuật và mở rộng |
| `docs/API.md` | Hợp đồng API chatbot và ví dụ gọi |

## Phạm vi triển khai

Phù hợp pilot một instance, kho tài liệu vừa phải. Giới hạn khởi điểm: 200 file, 10 triệu ký tự trích xuất mỗi tenant, 15 MB/file, 4 câu hỏi hoạt động và 3 sub-agent mỗi request. Đây là **giới hạn cấu hình**, không phải số lượng người dùng hoặc tốc độ đã được chứng minh.

Index đơn giản của LlamaIndex và BM25 nằm trong RAM; upload/xóa rebuild snapshot, tái dùng embedding cache. Khi kho lớn hoặc cần nhiều instance, chuyển sang vector database, PostgreSQL/Redis và worker ingestion riêng theo tài liệu kiến trúc. Hiện chưa có OCR, xử lý PDF, SSO/RBAC theo người dùng, hay phân quyền theo từng tài liệu.

Tài liệu kiến trúc nêu rõ các phần đã có trong code và các hạng mục mở rộng. LLM và ZeroTTS thật cần kiểm chứng với cấu hình mạng/model của đơn vị trước khi đánh giá chất lượng hoặc độ trễ.
