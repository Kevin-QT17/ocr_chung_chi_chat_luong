# API nhận diện chứng chỉ chất lượng

Ứng dụng FastAPI nhận ảnh, nhận diện nhóm logo/chứng chỉ và trích xuất các mốc ngày liên quan khi có đủ bằng chứng.

Phần kỹ thuật hiện tại đã được kiểm thử và được giữ ổn định. Không thay đổi model weights, threshold, bộ rule hoặc logic hợp nhất kết quả nếu chưa đánh giá lại hệ thống.

## 1. Pipeline

1. YOLO phát hiện vùng logo/chứng chỉ.
2. EasyOCR đọc vùng ngữ cảnh quanh bounding box và áp dụng luật phân loại.
3. Nếu nhánh detector/crop OCR chưa đủ bằng chứng, OCR toàn ảnh được dùng làm fallback.
4. Nếu các nhánh text vẫn chưa đủ bằng chứng, ORB + RANSAC visual matching được dùng như một fallback tham chiếu.
5. OCR toàn tài liệu và bộ trích xuất ngày trả về:
   - `issue_date`
   - `valid_from`
   - `expiry_date`
   - `decision_date`
6. Kết quả được hợp nhất và trả về qua API/giao diện web.

Các nhóm hiện hỗ trợ:

```text
haccp
fda
gmp
iso_22000
ocop
khac
```

## 2. Cấu trúc

```text
api/
├── app/
├── artifacts/
├── reference_logos/
├── tests/
├── weights/
├── .env.example
├── cai_dat_windows.ps1
├── chay_api.ps1
├── README.md
└── requirements.txt
```

Các thư mục `weights/`, `reference_logos/` và `artifacts/` là thành phần cần thiết của pipeline hiện tại.

## 3. Cài đặt trên Windows

Mở PowerShell:

```powershell
cd C:\thuc_tap_lazinet\ocr_chung_chi_chat_luong\api
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

Tạo môi trường ảo nếu chưa có:

```powershell
python -m venv .venv
```

Kích hoạt môi trường:

```powershell
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Khởi động

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Giao diện web tiếng Việt:

```text
http://127.0.0.1:8000/
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

## 5. Giao diện web

Trang `/` cho phép:

- chọn hoặc kéo thả ảnh;
- chạy nhận diện;
- xem loại chứng chỉ/logo;
- xem nguồn xác định kết quả;
- xem trạng thái phát hiện vùng logo;
- xem điểm nhận diện nội bộ;
- xem ngày cấp;
- xem ngày bắt đầu hiệu lực;
- xem ngày hết hạn;
- xem ngày quyết định/ký ban hành;
- mở phần JSON kỹ thuật khi cần.

## 6. Kiểm thử tự động

```powershell
python -m pytest -q
```

Kết quả kiểm tra cuối:

```text
12 passed
```

Nếu môi trường cũ chưa có `pytest`:

```powershell
python -m pip install pytest
```

Nên giữ `pytest` trong `api/requirements.txt` để máy khác có thể chạy test ngay sau khi cài dependencies.

## 7. Smoke test 6 nhóm

Bộ ảnh:

```text
C:\thuc_tap_lazinet\ocr_chung_chi_chat_luong\samples\mau_kiem_thu_6_nhom
```

Gồm:

- `fda.jpg`
- `gmp.jpg`
- `haccp.jpg`
- `iso_22000.jpg`
- `khac.jpg`
- `ocop.jpg`

Trong lần kiểm tra cuối, 6/6 mẫu trả về nhóm mong đợi.

Đây là smoke test chức năng, **không phải kết quả accuracy độc lập** và không nên ghi là “độ chính xác 100%”.

## 8. Ý nghĩa một số trường kết quả

`detector_status` có thể gồm:

```text
hit_known
hit_unclassified
no_detection
```

`classification_source` có thể gồm:

```text
detector_crop_ocr
full_page_ocr_fallback
visual_orb_fallback
unknown
```

Các trường ngày:

```text
issue_date
valid_from
expiry_date
decision_date
```

## 9. Giới hạn

- Detector có thể bỏ sót logo nhỏ/rất nhỏ.
- OCR phụ thuộc chất lượng ảnh và khả năng đọc được chữ.
- Visual matching chỉ là fallback dựa trên reference similarity.
- Dữ liệu các lớp hiếm còn ít.
- `khac` là nhóm open-set.
- Trích xuất ngày không suy đoán khi bằng chứng OCR không đủ.

## 10. Lưu ý về FDA

Trong taxonomy của dự án, `fda` biểu diễn dấu/logo/claim FDA xuất hiện trong dữ liệu, ví dụ `FDA REGISTERED`.

Kết quả của hệ thống không tự khẳng định rằng FDA đã cấp chứng nhận hoặc phê duyệt pháp lý cho sản phẩm.
