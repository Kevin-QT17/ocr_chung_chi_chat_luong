#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tạo và kiểm tra bộ gán bounding box logo chứng chỉ.

Chạy từ thư mục gốc project:
    python scripts/tao_bo_gan_bbox_logo.py --tao-bo-duyet
    python scripts/tao_bo_gan_bbox_logo.py --kiem-tra-ket-qua
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "du_lieu_logo"
SOURCE_CSV = DATA_ROOT / "nhan" / "duyet_logo.csv"
BBOX_DIR = DATA_ROOT / "bbox"
BBOX_CSV = BBOX_DIR / "bbox_logo.csv"
BBOX_HTML = BBOX_DIR / "duyet_bbox_logo.html"

FIELDS = [
    "stt_bbox", "ma_anh", "ma_san_pham", "ten_san_pham", "duong_dan_anh",
    "sha256", "url_anh", "nhan_goi_y", "so_logo_goi_y",
    "trang_thai_bbox", "so_bbox", "boxes_json", "ghi_chu_bbox",
]

def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

def tao_bo_duyet(force: bool = False):
    if not SOURCE_CSV.exists():
        raise SystemExit(f"Không tìm thấy: {SOURCE_CSV}")

    if BBOX_CSV.exists() and not force:
        raise SystemExit(
            f"{BBOX_CSV} đã tồn tại. Không ghi đè để tránh mất nhãn bbox.\n"
            "Nếu chắc chắn muốn khởi tạo lại, dùng --ghi-de."
        )

    rows = read_csv(SOURCE_CSV)
    positives = [r for r in rows if r.get("trang_thai_duyet") == "co_logo_chung_chi"]
    if not positives:
        raise SystemExit("Không tìm thấy ảnh có logo trong duyet_logo.csv")

    out = []
    for i, r in enumerate(positives, 1):
        out.append({
            "stt_bbox": str(i),
            "ma_anh": r["ma_anh"],
            "ma_san_pham": r["ma_san_pham"],
            "ten_san_pham": r["ten_san_pham"],
            "duong_dan_anh": r["duong_dan_anh"],
            "sha256": r["sha256"],
            "url_anh": r["url_anh"],
            "nhan_goi_y": r["logo_quan_sat_duoc"],
            "so_logo_goi_y": r["so_logo"],
            "trang_thai_bbox": "chua_duyet",
            "so_bbox": "0",
            "boxes_json": "[]",
            "ghi_chu_bbox": "",
        })
    write_csv(BBOX_CSV, out)

    print(f"Đã tạo {len(out)} ảnh cần gán bbox: {BBOX_CSV}")
    print("HTML giao diện đi kèm trong repo mẫu; nếu cần tạo lại HTML, dùng file duyet_bbox_logo.html đã cung cấp.")

def kiem_tra():
    if not BBOX_CSV.exists():
        raise SystemExit(f"Không tìm thấy: {BBOX_CSV}")

    rows = read_csv(BBOX_CSV)
    status = {"chua_duyet": 0, "da_gan_bbox": 0, "khong_co_logo": 0}
    errors = []
    total_boxes = 0

    for row in rows:
        st = row.get("trang_thai_bbox", "")
        status[st] = status.get(st, 0) + 1
        try:
            boxes = json.loads(row.get("boxes_json") or "[]")
        except Exception:
            errors.append(f"{row['ma_anh']}: boxes_json không hợp lệ")
            continue

        if not isinstance(boxes, list):
            errors.append(f"{row['ma_anh']}: boxes_json phải là list")
            continue

        total_boxes += len(boxes)
        if st == "da_gan_bbox" and not boxes:
            errors.append(f"{row['ma_anh']}: đã gán bbox nhưng không có box")
        if st == "khong_co_logo" and boxes:
            errors.append(f"{row['ma_anh']}: đánh dấu không có logo nhưng vẫn còn box")

        for j, b in enumerate(boxes, 1):
            required = {"label", "x", "y", "w", "h"}
            if not isinstance(b, dict) or not required.issubset(b):
                errors.append(f"{row['ma_anh']} box {j}: thiếu trường {sorted(required)}")
                continue
            if b["w"] <= 0 or b["h"] <= 0 or b["x"] < 0 or b["y"] < 0:
                errors.append(f"{row['ma_anh']} box {j}: tọa độ/kích thước không hợp lệ")

    print(f"Tổng ảnh bbox: {len(rows)}")
    print(f"Đã gán bbox: {status.get('da_gan_bbox', 0)}")
    print(f"Thực tế không có logo: {status.get('khong_co_logo', 0)}")
    print(f"Chưa duyệt: {status.get('chua_duyet', 0)}")
    print(f"Tổng số box: {total_boxes}")

    if errors:
        print("\nCẢNH BÁO:")
        for e in errors[:50]:
            print(" -", e)
        if len(errors) > 50:
            print(f" ... và {len(errors)-50} lỗi khác")
        raise SystemExit(1)

    if status.get("chua_duyet", 0):
        raise SystemExit("\nBộ bbox chưa hoàn tất.")
    print("\nBộ bbox hợp lệ và đã hoàn tất.")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tao-bo-duyet", action="store_true")
    p.add_argument("--kiem-tra-ket-qua", action="store_true")
    p.add_argument("--ghi-de", action="store_true")
    args = p.parse_args()

    if args.tao_bo_duyet:
        tao_bo_duyet(args.ghi_de)
    elif args.kiem_tra_ket_qua:
        kiem_tra()
    else:
        p.print_help()

if __name__ == "__main__":
    main()
