---
name: boi-thuong-khieu-nai
description: Quy trình tiếp nhận, thẩm định thời hiệu khiếu nại và khung tỷ lệ bồi thường thiệt hại dịch vụ bưu chính VNPost.
version: 1.0.0
author: Ban Chăm Sóc Khách Hàng VNPost
triggers:
  - bồi thường bưu gửi
  - khiếu nại chuyển phát chậm
  - hàng bị hỏng khi gửi
  - quy trình đền bù mất hàng
allowed_tools:
  - track_item
  - create_draft_complaint
---

# QUY TRÌNH TIẾP NHẬN KHIẾU NẠI VÀ BỒI THƯỜNG THIỆT HẠI VNPOST

## 1. Thời hiệu Khiếu nại Hợp lệ
- **Dịch vụ trong nước:** 06 tháng kể từ ngày kết thúc chỉ tiêu thời gian phát bưu gửi.
- **Dịch vụ quốc tế:** 12 tháng kể từ ngày bưu phẩm được chấp nhận tại bưu cục gốc.
- Các yêu cầu gửi sau thời hiệu trên sẽ tự động bị hệ thống từ chối tiếp nhận theo quy định Luật Bưu chính.

## 2. Cam kết Thời gian Giải quyết (SLA)
- **Nội địa:** Tối đa 20 ngày làm việc kể từ thời điểm tiếp nhận đầy đủ hồ sơ hợp lệ.
- **Quốc tế:** Tối đa 30 ngày làm việc (do cần trao đổi và xác minh qua bưu chính nước bạn).

## 3. Khung Tỷ lệ Bồi thường Cơ bản
| Loại hình sự cố | Dịch vụ EMS Trong nước | Dịch vụ Bưu kiện thường |
| :--- | :--- | :--- |
| **Mất mát / Hư hỏng hoàn toàn (Có khai giá)** | 100% giá trị khai giá theo chứng từ hợp lệ | 100% giá trị khai giá theo chứng từ hợp lệ |
| **Mất mát / Hư hỏng hoàn toàn (Không khai giá)** | Tối đa 10 lần cước dịch vụ chính đã thu | Tối đa 04 lần cước dịch vụ chính đã thu |
| **Chậm chỉ tiêu thời gian phát** | Hoàn trả 100% cước dịch vụ đã thu | Hoàn trả 100% cước dịch vụ đã thu |
| **Hàng đóng gói không chuẩn** | Miễn trừ trách nhiệm bồi thường | Miễn trừ trách nhiệm bồi thường |
