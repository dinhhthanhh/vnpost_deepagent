---
name: tra_cuu_buu_gui
description: Kỹ năng tra cứu hành trình, giải mã mã trạng thái vận đơn bưu chính và thời gian phát dự kiến của VNPost.
version: 1.0.0
author: Tổng công ty Bưu điện Việt Nam (VNPost)
triggers:
  - tra cứu đơn hàng
  - kiểm tra mã bưu gửi
  - bưu phẩm đang ở đâu
  - mã vận đơn
allowed_tools:
  - track_item
---

# KỸ NĂNG TRA CỨU HÀNH TRÌNH BƯU GỬI VNPOST

## 1. Định dạng Mã Bưu gửi Chuẩn UPU
Mã bưu phẩm bưu kiện của VNPost tuân theo quy chuẩn quốc tế của Liên minh Bưu chính Thế giới (UPU):
- **Cấu trúc:** Gồm 13 ký tự: `[2 chữ cái đầu] + [9 chữ số] + [VN]`
- **Ký tự đầu quy định dịch vụ:**
  - `E...VN` (ví dụ: `EB123456789VN`, `EI123456789VN`): Dịch vụ Chuyển phát nhanh EMS.
  - `C...VN` (ví dụ: `CP123456789VN`): Dịch vụ Bưu phẩm / Bưu kiện bảo đảm.
  - `R...VN`: Thư bảo đảm quốc tế.

## 2. Bảng Giải mã Mã Trạng thái Vận hành (BCCP Event Codes)
| Mã sự kiện | Tên trạng thái | Diễn giải chi tiết cho khách hàng |
| :--- | :--- | :--- |
| **J00** | Chấp nhận bưu gửi | Bưu tá hoặc bưu cục đã tiếp nhận kiện hàng từ người gửi. |
| **J02** | Rời bưu cục gốc | Kiện hàng đang trên xe chuyên dụng chuyển về Trung tâm Khai thác. |
| **J04** | Nhập bưu cục phát | Kiện hàng đã đến bưu cục phụ trách giao hàng tại địa chỉ người nhận. |
| **J06** | Đang giao hàng | Bưu tá đang trực tiếp đi phát kiện hàng tới người nhận. |
| **J12** | Giao thành công | Khách hàng đã ký nhận bưu gửi hoàn tất. |
| **J14** | Giao không thành công | Người nhận vắng mặt, sai số điện thoại hoặc hẹn giao lại vào ca sau. |

## 3. Quy trình Trả lời Khách hàng
1. Luôn trích dẫn chính xác mã vận đơn và ngày giờ cập nhật gần nhất.
2. Nếu bưu gửi đang ở trạng thái **J06**, thông báo khách hàng chú ý nghe máy từ bưu tá VNPost.
3. Nếu bưu gửi ở trạng thái **J14**, hướng dẫn khách hàng cách hẹn lại giờ giao hoặc liên hệ hotline bưu cục phát.
