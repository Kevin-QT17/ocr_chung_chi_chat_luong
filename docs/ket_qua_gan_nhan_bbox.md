# Kết quả audit và gán bounding box

- Tổng ảnh từng được đánh dấu có logo: **101**
- Đã gán bounding box: **94 ảnh**
- Audit lại thành không có logo: **7 ảnh**
- Chưa duyệt bbox: **0 ảnh**
- Tổng bounding box: **103**

## 7 ảnh được sửa từ dương tính thành không có logo

- `anh_000086`
- `anh_000087`
- `anh_000110`
- `anh_000301`
- `anh_000739`
- `anh_000740`
- `anh_000741`

Các ảnh này được kiểm tra lại ở bước chuẩn bị object detection và không thấy logo/chứng chỉ tương ứng hiển thị rõ trong ảnh.

## Phân bố bounding box

- `khac`: 55
- `ocop`: 34
- `haccp`: 5
- `gmp`: 4
- `iso_22000`: 3
- `fda`: 2

## File sử dụng

- `data/du_lieu_logo/bbox/bbox_logo.csv`: nhãn bounding box.
- `data/du_lieu_logo/bbox/duyet_bbox_logo.html`: giao diện xem/chỉnh lại các box đã gán.
- `duyet_logo_da_audit_bbox.csv`: bản nhãn cấp ảnh đã sửa sau audit bbox.

> Khi đưa vào project, nên thay `data/du_lieu_logo/nhan/duyet_logo.csv` bằng bản audit sau khi đã lưu backup bản cũ.
