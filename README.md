# OCR Chứng chỉ Chất lượng – Hathyo

Dự án thực tập phục vụ bài toán thu thập dữ liệu và chuẩn bị dữ liệu cho hệ thống nhận diện logo/chứng chỉ chất lượng trên ảnh sản phẩm, hướng tới các bước tiếp theo gồm Computer Vision, OCR ngày cấp/ngày hết hạn và triển khai API.

## 1. Mục tiêu

Các hạng mục của bài toán:

1. Tìm hiểu các loại logo/chứng chỉ chất lượng.
2. Thu thập dữ liệu sản phẩm và ảnh từ Hathyo.
3. Chuẩn hóa, kiểm tra và loại trùng dữ liệu ảnh.
4. Xây dựng công cụ gán nhãn.
5. Phân loại ảnh có/không có logo chứng chỉ và gán loại logo quan sát được.
6. Thử nghiệm mô hình Computer Vision nhận diện logo.
7. OCR ngày cấp và ngày hết hạn trên chứng chỉ.
8. Triển khai API bằng Python FastAPI hoặc Java Spring Boot.

## 2. Tiến độ hiện tại

### Đã hoàn thành

- Thu thập dữ liệu sản phẩm từ Hathyo.
- Thu thập metadata và ảnh gallery sản phẩm.
- Kiểm tra định dạng ảnh và trạng thái tải.
- Loại trùng ảnh bằng SHA-256.
- Xây dựng công cụ duyệt/gán nhãn chạy bằng HTML.
- Hoàn tất duyệt **723/723 ảnh**.
- Hoàn tất phân loại có/không có logo chứng chỉ.
- Gán loại logo quan sát được cho các ảnh có logo.

### Kết quả dữ liệu

| Hạng mục | Kết quả |
|---|---:|
| Sản phẩm | 304 |
| Bản ghi ảnh phát hiện | 827 |
| Ảnh tải thành công / ảnh duy nhất để duyệt | 723 |
| Ảnh trùng SHA-256 | 102 |
| Ảnh không thể tải công khai | 2 |
| Ảnh đã duyệt | 723 / 723 |
| Có logo chứng chỉ | 101 |
| Không có logo chứng chỉ | 622 |
| Cần kiểm tra lại | 0 |
| Chưa duyệt | 0 |

### Phân bố nhãn logo hiện tại

| Nhãn | Số ảnh |
|---|---:|
| `khac` | 54 |
| `ocop` | 36 |
| `haccp` | 5 |
| `gmp` | 4 |
| `iso_22000` | 3 |
| `fda` | 2 |

> Một ảnh có thể chứa nhiều loại logo nên tổng số nhãn có thể lớn hơn số ảnh có logo.

### Danh mục nhãn đã chuẩn bị

`tcvn`, `haccp`, `vietgap`, `globalgap`, `fda`, `ce`, `oeko_tex`, `brcgs`,
`rainforest_alliance`, `ocop`, `usda_organic`, `eu_organic`, `halal`, `fcc`,
`rohs`, `gmp`, `iso_22000`, `khac`.

## 3. Cấu trúc thư mục

```text
ocr_chung_chi_chat_luong/
├── README.md
├── requirements.txt
├── .gitignore
│
├── scripts/
│   ├── thu_thap_anh_hathyo.py
│   └── tao_bo_duyet_logo.py
│
└── data/
    └── du_lieu_logo/
        ├── anh_goc/
        │   ├── san_pham_0001/
        │   ├── san_pham_0002/
        │   └── ...
        │
        ├── bang_du_lieu/
        │   ├── san_pham.csv
        │   └── anh.csv
        │
        └── nhan/
            ├── duyet_logo.csv
            └── duyet_logo.html
```

## 4. Các file chính

### `scripts/thu_thap_anh_hathyo.py`

Script thu thập dữ liệu Hathyo, bao gồm:

- kiểm tra môi trường;
- kiểm tra `robots.txt`;
- khảo sát danh sách sản phẩm và URL ảnh;
- tải ảnh;
- giới hạn kích thước ảnh;
- retry khi tải lỗi;
- kiểm tra định dạng thực của ảnh;
- tính SHA-256;
- phát hiện ảnh trùng;
- ghi metadata vào CSV;
- kiểm tra lại tính toàn vẹn dữ liệu.

### `scripts/tao_bo_duyet_logo.py`

Script tạo và kiểm tra bộ gán nhãn:

- sinh `duyet_logo.csv`;
- sinh `duyet_logo.html`;
- duyệt ảnh bằng giao diện trình duyệt;
- chọn trạng thái có/không logo;
- chọn loại logo;
- nhập số logo;
- đánh giá chất lượng ảnh;
- ghi chú;
- xuất kết quả CSV.

> **Lưu ý:** dữ liệu nhãn hiện tại đã hoàn tất. Không nên chạy lại `--tao-bo-duyet` lên dữ liệu chính nếu chưa backup vì thao tác này có thể khởi tạo lại bộ duyệt.

## 5. Yêu cầu môi trường

- Python **3.10+**
- Hai script hiện tại chỉ sử dụng **Python Standard Library**, chưa cần package bên thứ ba.

Cài dependencies (hiện tại lệnh này không cài thêm thư viện nào):

```bash
pip install -r requirements.txt
```

## 6. Cách chạy

Chạy lệnh từ thư mục `ocr_chung_chi_chat_luong`.

### Kiểm tra môi trường thu thập dữ liệu

```bash
python scripts/thu_thap_anh_hathyo.py --kiem-tra-moi-truong
```

### Khảo sát sản phẩm và URL ảnh

```bash
python scripts/thu_thap_anh_hathyo.py --khao-sat
```

### Tải ảnh

```bash
python scripts/thu_thap_anh_hathyo.py --tai-anh
```

### Kiểm tra kết quả tải ảnh

```bash
python scripts/thu_thap_anh_hathyo.py --kiem-tra-ket-qua
```

### Kiểm tra bộ gán nhãn

```bash
python scripts/tao_bo_duyet_logo.py --kiem-tra-ket-qua
```

Để xem/chỉnh nhãn thủ công, mở:

```text
data/du_lieu_logo/nhan/duyet_logo.html
```

## 7. Quy ước gán nhãn

Các thành phần **không được tính là logo chứng chỉ**:

- logo thương hiệu/sản phẩm;
- QR code;
- barcode;
- cờ quốc gia;
- icon trang trí/quảng cáo;
- con dấu doanh nghiệp hoặc dấu hành chính thông thường.

Các logo/chứng nhận phù hợp danh mục được gán class tương ứng. Trường hợp là logo/chứng nhận hợp lệ nhưng chưa có class riêng được gán `khac`.

## 8. Công việc tiếp theo

- [ ] Chuẩn bị dữ liệu cho mô hình Computer Vision.
- [ ] Xác định hướng classification / multi-label classification / object detection.
- [ ] Thử nghiệm mô hình nhận diện logo.
- [ ] Đánh giá precision, recall, F1/mAP phù hợp với bài toán.
- [ ] OCR nội dung chứng chỉ.
- [ ] Trích xuất ngày cấp.
- [ ] Trích xuất ngày hết hạn.
- [ ] Xây dựng API inference bằng FastAPI hoặc Spring Boot.

## 9. Trạng thái báo cáo lần 1

**Hoàn thành giai đoạn thu thập, chuẩn hóa và gán nhãn dữ liệu.**

Pipeline hiện tại:

```text
Hathyo
  → thu thập sản phẩm
  → thu thập URL ảnh
  → tải và kiểm tra ảnh
  → loại trùng SHA-256
  → lưu metadata
  → tạo công cụ gán nhãn
  → duyệt 723/723 ảnh
  → phân loại có/không logo
  → gán loại logo
```

Bước tiếp theo: **thử nghiệm Computer Vision nhận diện logo chứng chỉ**.
