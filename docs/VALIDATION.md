# Kiểm tra bộ mã nguồn phiên bản 1.0.0

Ngày kiểm tra: 13/10/2026. Môi trường Python 3.12 trên Linux; hướng dẫn Windows được cung cấp nhưng chưa chạy trực tiếp trên Windows.

| Kiểm tra | Kết quả |
|---|---|
| Pytest backend | 50 passed |
| Node frontend/WAV/SSE | 11 passed |
| Ruff | All checks passed |
| Dependency consistency | pip check không phát hiện xung đột |
| Vite production build | Thành công, có `frontend/dist` trong ZIP |
| Browser desktop và mobile | Chat, nguồn, reload phiên, không lỗi JS hoặc tràn ngang trong bài thử |
| Tài liệu kiến trúc Word | Đã render và kiểm tra 10 trang |

## Phạm vi kiểm thử backend

Test thực sự khởi tạo `create_deep_agent`, các graph LangChain và index/retriever LlamaIndex. Model demo là kịch bản; test contract bổ sung chạy `ChatOpenAI` và `OpenAIEmbedding` thật với HTTP mô phỏng. Không thay các framework bằng implementation giả.

Các kiểm tra bao gồm:

- Cả native `task` của Deep Agents và `parallel_tasks` đều chạy sub-agent đồng thời, xác nhận qua trace bắt đầu/kết thúc chồng nhau.
- Budget task, semaphore, timeout, hủy request, một sub-agent lỗi, và đầu ra JSON array hợp lệ.
- Hai request/tenant song song giữ nguồn riêng; các request cùng phiên giữ đủ lượt hội thoại.
- TXT/DOCX, bảng và vị trí nguồn, chống đường dẫn filename, file sai loại, file vượt giới hạn và DOCX quá lớn sau giải nén.
- Upload trùng, lưu/tải lại index, xóa tài liệu, rollback khi indexing lỗi và bắt cấu hình model/chunk đã đổi.
- Cache embedding tái dùng vector và tách namespace query/document.
- Chặn mã nguồn không có thật, báo thiếu bằng chứng và giữ đáp án chữ khi TTS lỗi.
- Calculator chạy số học đúng và từ chối code, thuộc tính, tên biến hoặc phép tính vượt giới hạn.
- Contract TTS dùng đúng prefix `/zero-tts`, endpoint, payload, WAV, voices và chunk streaming; lỗi không lộ thông tin provider.
- Contract LLM đi qua bốn lượt model trong bài tra cứu mẫu; embedding dùng đúng model engine tùy chỉnh và cả lần index/query.

## Phạm vi kiểm thử frontend

11 test Node bao gồm WAV bị chia thành chunk 1, 2, 7, 13, 44 và 1.000 byte; header có JUNK; mono/stereo; sample rate 16 kHz và 22,05 kHz; data length chưa biết; phát hiện dữ liệu bị cắt; codec không hỗ trợ; và SSE có JSON chưa đủ frame.

Browser thử trực tiếp frontend build với backend demo đang chạy: tra cứu nhận một nguồn, reload giữ lại nguồn và hội thoại, không phát hiện page error hoặc tràn ngang ở viewport mobile 390 px. Screenshots chỉ dùng để kiểm tra nội bộ, không nằm trong bản ZIP.

## Những số đo chưa có

Chưa dùng LLM với trọng số thật hoặc gọi ZeroTTS VNPost thật. Các test HTTP mô phỏng chứng minh hợp đồng tích hợp, không chứng minh khả năng truy cập mạng, tool calling của model bạn chọn, chất lượng tiếng Việt, tỷ lệ đúng hay độ trễ voice thực tế. Chưa kiểm tra Docker build/runtime hoặc chịu tải production trong môi trường này.

Trước khi triển khai thật, điền cấu hình, chạy `check_services.py --live --tts`, nạp tài liệu của đơn vị và đo trên bộ câu hỏi đã gán đáp án. Không dùng kết quả demo làm tỷ lệ đúng nghiệp vụ. `evaluate_retrieval.py` đã có để đo Recall@K/MRR@K và p50/p95 của retrieval; phần chấm đáp án cuối cùng vẫn cần người nghiệp vụ.

Dependency chính: Deep Agents 0.7.24, LangChain 1.4.5, LangChain OpenAI 1.7.1, LlamaIndex Core 0.14.25, LlamaIndex OpenAI Embeddings 0.7.0, FastAPI 0.143.0 và HTTPX 0.28.1. `requirements.lock.txt` ghi các package được cài trong môi trường kiểm tra; `frontend/package-lock.json` khóa dependency giao diện.
