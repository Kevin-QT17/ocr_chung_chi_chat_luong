# Hệ thống nhận diện chứng chỉ chất lượng từ hình ảnh

Dự án thực tập xây dựng quy trình từ **thu thập dữ liệu → gán nhãn → chuẩn bị dữ liệu Computer Vision → nhận diện logo/chứng chỉ → OCR ngày liên quan → triển khai FastAPI**.

Hệ thống hiện hỗ trợ các nhóm mục tiêu:

- `haccp`
- `fda`
- `gmp`
- `iso_22000`
- `ocop`
- `khac`

> `khac` được dùng cho trường hợp không đủ bằng chứng để xếp vào các nhóm mục tiêu hoặc thuộc nhóm ngoài taxonomy hiện tại.

## 1. Mục tiêu

1. Tìm hiểu các loại logo/chứng chỉ chất lượng xuất hiện trên ảnh sản phẩm và tài liệu.
2. Thu thập, chuẩn hóa và loại trùng dữ liệu ảnh từ Hathyo.
3. Xây dựng quy trình duyệt nhãn và gán bounding box cho vùng logo.
4. Chuẩn bị các bộ dữ liệu phục vụ thử nghiệm Computer Vision.
5. Phát hiện vùng logo/chứng chỉ bằng YOLO.
6. Kết hợp OCR và luật phân loại để nhận diện nhóm chứng chỉ.
7. Trích xuất ngày cấp, ngày hiệu lực, ngày hết hạn và ngày quyết định/ký ban hành khi có đủ bằng chứng.
8. Triển khai hệ thống bằng Python FastAPI và cung cấp giao diện web tiếng Việt.

## 2. Kết quả dữ liệu

### 2.1. Dữ liệu thu thập từ Hathyo

| Hạng mục | Kết quả |
|---|---:|
| Sản phẩm | 304 |
| Bản ghi ảnh phát hiện | 827 |
| Ảnh vật lý duy nhất | 723 |
| Ảnh trùng SHA-256 | 102 |
| Ảnh không thể tải công khai | 2 |
| Ảnh đã duyệt | 723 / 723 |
| Có logo/chứng chỉ | 94 |
| Không có logo/chứng chỉ | 629 |
| Cần kiểm tra lại | 0 |
| Chưa duyệt | 0 |

File nhãn chính:

```text
data/du_lieu_logo/nhan/duyet_logo.csv
```

### 2.2. Bounding box

File bounding box chính:

```text
data/du_lieu_logo/bbox/bbox_logo.csv
```

Thống kê:

- 94 ảnh dương tính.
- 103 bounding box.

Phân bố bounding box:

| Nhãn | Số bbox |
|---|---:|
| `khac` | 55 |
| `ocop` | 34 |
| `haccp` | 5 |
| `gmp` | 4 |
| `iso_22000` | 3 |
| `fda` | 2 |

Dữ liệu mất cân bằng mạnh, đặc biệt ở các lớp `haccp`, `fda`, `gmp` và `iso_22000`.

## 3. Các bộ dữ liệu đã chuẩn bị

### YOLO đa lớp

Mapping:

```text
0: haccp
1: fda
2: gmp
3: iso_22000
4: ocop
5: khac
```

### YOLO nhị phân

Bài toán detector được quy về một lớp:

```text
logo_chung_chi
```

Thống kê:

- 282 ảnh.
- 94 ảnh dương tính.
- 188 ảnh âm tính.
- 103 bounding box.

### Dữ liệu crop logo cho phân loại

Thư mục:

```text
data/logo_classifier_raw
```

Tổng cộng 103 crop:

- train: 71
- validation: 15
- test: 17

## 4. Kết quả thử nghiệm chính

### 4.1. Detector logo

Detector được dùng trong hệ thống cuối là YOLO11s với kích thước suy luận 960.

Kết quả đánh giá chính:

| Chỉ số | Giá trị |
|---|---:|
| Precision | ~0.489 |
| Recall | ~0.235 |
| mAP@50 | ~0.193 |
| mAP@50:95 | ~0.097 |

Ngưỡng confidence sử dụng:

```text
0.4
```

Phân tích cho thấy hạn chế chính của detector là các logo **nhỏ và rất nhỏ**. Vì vậy hệ thống cuối không phụ thuộc vào detector duy nhất mà sử dụng thêm OCR toàn ảnh và visual matching fallback.

### 4.2. Phân loại logo bằng OCR theo ngữ cảnh

OCR trên crop quá chặt có thể làm mất phần chữ nhận dạng quan trọng. Sau khi mở rộng vùng crop theo ngữ cảnh và áp dụng luật phân loại chặt chẽ, kết quả trên tập test 17 crop:

| Chỉ số | Giá trị |
|---|---:|
| Accuracy | ~0.941 |
| Macro F1 | ~0.809 |
| Precision known/unknown | 1.000 |
| Recall known/unknown | ~0.909 |
| F1 known/unknown | ~0.952 |

Kết quả theo lớp trên tập này:

- HACCP: 1/1
- GMP: 1/1
- ISO 22000: 1/1
- OCOP: 7/8
- Khác: 6/6
- FDA: không có mẫu trong tập test

> Tập test nhỏ và mất cân bằng nên các chỉ số trên không đại diện cho mọi dữ liệu ngoài thực tế.

## 5. Trích xuất ngày

Các trường đầu ra:

```text
issue_date
valid_from
expiry_date
decision_date
```

Hệ thống ưu tiên các ngày có ngữ cảnh liên quan đến chứng chỉ và loại bỏ những ngày không phù hợp như:

- ngày nhận mẫu;
- khoảng thời gian thử nghiệm;
- ngày báo cáo kiểm nghiệm;
- ngày sản xuất / hạn sử dụng sản phẩm khi không liên quan đến chứng chỉ.

Các chỉ số trích xuất ngày hiện được xem là **development metrics**, vì luật đã được tinh chỉnh trên cùng bộ tham chiếu trong quá trình phát triển; đây chưa phải benchmark độc lập bên ngoài.

Nếu OCR không đủ bằng chứng, hệ thống để trường ngày trống thay vì tự suy đoán.

## 6. Kiến trúc hệ thống cuối

```text
Ảnh đầu vào
│
├── YOLO phát hiện vùng logo
│   └── crop theo ngữ cảnh
│       └── EasyOCR + luật phân loại
│
├── EasyOCR toàn ảnh + luật phân loại
│
├── ORB + RANSAC visual matching khi các nhánh text chưa đủ bằng chứng
│
└── OCR toàn tài liệu + bộ trích xuất ngày
        │
        ▼
   Tổng hợp kết quả
        │
        ▼
 FastAPI + giao diện web tiếng Việt
```

Các nguồn phân loại trong API có thể gồm:

```text
detector_crop_ocr
full_page_ocr_fallback
visual_orb_fallback
unknown
```

Visual matching là cơ chế fallback dựa trên ảnh tham chiếu. Kết quả của nhánh này không nên được diễn giải thành bằng chứng cho khả năng tổng quát hóa mạnh trên dữ liệu bên ngoài.

## 7. Cấu trúc thư mục

```text
ocr_chung_chi_chat_luong/
├── api/
│   ├── app/
│   ├── artifacts/
│   ├── reference_logos/
│   ├── tests/
│   ├── weights/
│   ├── .env.example
│   ├── cai_dat_windows.ps1
│   ├── chay_api.ps1
│   ├── README.md
│   └── requirements.txt
│
├── data/
│   ├── du_lieu_logo/
│   ├── logo_classifier_raw/
│   ├── yolo_logo/
│   ├── yolo_logo_binary/
│   └── yolo_logo_multiclass_aug/
│
├── docs/
│   └── ket_qua_gan_nhan_bbox.md
│
├── samples/
│   └── mau_kiem_thu_6_nhom/
│
├── scripts/
│   ├── thu_thap_anh_hathyo.py
│   ├── tao_bo_duyet_logo.py
│   ├── tao_bo_gan_bbox_logo.py
│   ├── tao_dataset_logo_classifier.py
│   ├── tao_dataset_yolo_binary.py
│   ├── tao_dataset_yolo_binary_ngu_canh.py
│   ├── tao_dataset_yolo_multiclass.py
│   └── tao_dataset_yolo_multiclass_can_bang.py
│
├── .gitignore
├── README.md
└── requirements.txt
```

## 8. Các thành phần chính

### Thu thập dữ liệu

```text
scripts/thu_thap_anh_hathyo.py
```

Thực hiện khảo sát sản phẩm, tải ảnh, kiểm tra định dạng, tính SHA-256, loại trùng và lưu metadata.

### Duyệt nhãn

```text
scripts/tao_bo_duyet_logo.py
```

Dùng trong giai đoạn tạo bộ duyệt/gán nhãn. File nhãn chính hiện tại đã hoàn tất; không nên khởi tạo lại bộ duyệt trên dữ liệu chính nếu chưa sao lưu.

### Gán bounding box

```text
scripts/tao_bo_gan_bbox_logo.py
```

Hỗ trợ tạo dữ liệu bounding box cho logo/chứng chỉ.

### Chuẩn bị dataset

Các script trong `scripts/tao_dataset_*.py` dùng để tạo các bộ dữ liệu phục vụ detector và thử nghiệm phân loại.

### API

```text
api/
```

Chứa hệ thống inference cuối, model weights, reference logo, artifact, test và giao diện web.

## 9. Cài đặt API trên Windows

Mở PowerShell:

```powershell
cd C:\thuc_tap_lazinet\ocr_chung_chi_chat_luong\api
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

Tạo môi trường ảo nếu chưa có:

```powershell
python -m venv .venv
```

Kích hoạt:

```powershell
.\.venv\Scripts\Activate.ps1
```

Cài dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Khởi động API:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 10. Địa chỉ sử dụng

Giao diện web tiếng Việt:

```text
http://127.0.0.1:8000/
```

Swagger dành cho kiểm thử API:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

## 11. Kiểm thử

Chạy unit test:

```powershell
cd C:\thuc_tap_lazinet\ocr_chung_chi_chat_luong\api
python -m pytest -q
```

Kết quả kiểm tra cuối:

```text
12 passed
```

Bộ ảnh smoke test:

```text
samples/mau_kiem_thu_6_nhom/
```

Gồm:

```text
fda.jpg
gmp.jpg
haccp.jpg
iso_22000.jpg
khac.jpg
ocop.jpg
```

Trong lần kiểm tra cuối, **6/6 ảnh smoke test được trả về đúng nhóm mong đợi**.

> Đây là kiểm thử chức năng có chọn mẫu, không phải phép đo accuracy độc lập. Một số mẫu có liên hệ với dữ liệu/reference dùng trong quá trình phát triển, vì vậy không diễn giải kết quả 6/6 thành “độ chính xác 100%”.

## 12. Giới hạn hiện tại

- Dữ liệu mất cân bằng mạnh giữa các lớp.
- Số mẫu HACCP, FDA, GMP và ISO 22000 còn ít.
- Detector còn yếu với logo nhỏ và rất nhỏ.
- Một số ảnh phải dựa vào OCR toàn ảnh thay vì detector.
- Visual matching phù hợp làm fallback nhưng chưa chứng minh khả năng tổng quát hóa trên dữ liệu ngoài.
- `khac` là nhóm open-set không đồng nhất về ngữ nghĩa.
- Trích xuất ngày phụ thuộc chất lượng OCR và bố cục tài liệu.
- Các chỉ số date extraction hiện là development metrics, chưa phải đánh giá độc lập.

## 13. Lưu ý về nhãn FDA

Trong taxonomy của dự án, `fda` đại diện cho dấu/logo/claim liên quan đến FDA xuất hiện trong dữ liệu, ví dụ dạng `FDA REGISTERED`.

Kết quả nhận diện chỉ phản ánh taxonomy nhận dạng của dự án, **không tự khẳng định giá trị pháp lý hoặc việc FDA đã chứng nhận/phê duyệt sản phẩm**.

## 14. Trạng thái dự án

Đã hoàn thành:

- thu thập và chuẩn hóa dữ liệu;
- loại trùng ảnh;
- duyệt và chỉnh nhãn;
- gán bounding box;
- chuẩn bị dataset;
- thử nghiệm detector;
- OCR và phân loại logo;
- visual matching fallback;
- trích xuất ngày;
- FastAPI;
- giao diện web tiếng Việt;
- unit test;
- smoke test 6 nhóm.

Phần kỹ thuật hiện tại được giữ ổn định để phục vụ bàn giao và báo cáo thực tập.
