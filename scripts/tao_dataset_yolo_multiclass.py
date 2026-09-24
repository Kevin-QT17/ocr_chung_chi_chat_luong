from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent

BBOX_CSV = PROJECT_ROOT / "data" / "du_lieu_logo" / "bbox" / "bbox_logo.csv"
IMAGE_LABEL_CSV = PROJECT_ROOT / "data" / "du_lieu_logo" / "nhan" / "duyet_logo.csv"

OUTPUT_DIR = PROJECT_ROOT / "data" / "yolo_logo"
ZIP_PATH = PROJECT_ROOT / "yolo_logo_dataset.zip"

# ID class cố định. Không được tự đổi thứ tự sau khi train.
CLASS_NAMES = [
    "haccp",
    "fda",
    "gmp",
    "iso_22000",
    "ocop",
    "khac",
]

CLASS_TO_ID = {name: idx for idx, name in enumerate(CLASS_NAMES)}

SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15

# Dùng khoảng 2 ảnh âm tính / 1 ảnh dương tính.
# Dataset hiện có quá nhiều ảnh âm nên không lấy cả 629 ảnh cho baseline đầu tiên.
NEGATIVE_RATIO = 2.0


def read_csv(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def resolve_image_path(raw_path: str) -> Path:
    """
    CSV cũ lưu đường dẫn Windows bằng dấu \\.
    Chuẩn hóa để chạy được trên Windows/Linux/Colab.
    """
    normalized = raw_path.replace("\\", "/")
    p = Path(normalized)

    if p.is_absolute():
        return p

    return PROJECT_ROOT / p


def parse_boxes(row):
    raw = row.get("boxes_json") or "[]"

    try:
        boxes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{row.get('ma_anh')}: boxes_json không hợp lệ: {exc}"
        )

    if not isinstance(boxes, list):
        raise ValueError(f"{row.get('ma_anh')}: boxes_json không phải list")

    return boxes


def validate_bbox_dataset(bbox_rows, label_rows):
    errors = []
    warnings = []

    bbox_by_image = {}
    total_boxes = 0
    label_counter = Counter()

    for row in bbox_rows:
        image_id = row["ma_anh"]

        if image_id in bbox_by_image:
            errors.append(f"Trùng ma_anh trong bbox CSV: {image_id}")
            continue

        bbox_by_image[image_id] = row

        status = row.get("trang_thai_bbox", "")
        boxes = parse_boxes(row)

        try:
            declared = int(row.get("so_bbox") or 0)
        except ValueError:
            errors.append(f"{image_id}: so_bbox không phải số")
            continue

        if declared != len(boxes):
            errors.append(
                f"{image_id}: so_bbox={declared} nhưng boxes_json có {len(boxes)} box"
            )

        if status == "da_gan_bbox" and len(boxes) == 0:
            errors.append(f"{image_id}: da_gan_bbox nhưng không có box")

        if status == "khong_co_logo" and len(boxes) != 0:
            errors.append(f"{image_id}: khong_co_logo nhưng vẫn có box")

        if status == "chua_duyet":
            errors.append(f"{image_id}: bbox vẫn chưa duyệt")

        if status not in {"da_gan_bbox", "khong_co_logo"}:
            errors.append(f"{image_id}: trạng thái bbox lạ: {status}")

        image_path = resolve_image_path(row["duong_dan_anh"])

        if not image_path.exists():
            errors.append(f"{image_id}: thiếu ảnh {image_path}")
            continue

        try:
            with Image.open(image_path) as img:
                image_width, image_height = img.size
        except Exception as exc:
            errors.append(f"{image_id}: không đọc được ảnh: {exc}")
            continue

        for index, box in enumerate(boxes, 1):
            label = box.get("label")

            if label not in CLASS_TO_ID:
                errors.append(
                    f"{image_id} box {index}: class không hợp lệ: {label}"
                )
                continue

            label_counter[label] += 1
            total_boxes += 1

            required = ["x", "y", "w", "h"]
            if any(k not in box for k in required):
                errors.append(f"{image_id} box {index}: thiếu tọa độ")
                continue

            try:
                x = float(box["x"])
                y = float(box["y"])
                w = float(box["w"])
                h = float(box["h"])
            except (TypeError, ValueError):
                errors.append(f"{image_id} box {index}: tọa độ không phải số")
                continue

            if x < 0 or y < 0 or w <= 0 or h <= 0:
                errors.append(
                    f"{image_id} box {index}: tọa độ/kích thước không hợp lệ"
                )
                continue

            # Cho phép sai số tối đa 2 pixel do làm tròn khi vẽ.
            if x + w > image_width + 2 or y + h > image_height + 2:
                errors.append(
                    f"{image_id} box {index}: box vượt kích thước ảnh "
                    f"({image_width}x{image_height})"
                )

    labels_by_image = {r["ma_anh"]: r for r in label_rows}

    for image_id, bbox_row in bbox_by_image.items():
        if image_id not in labels_by_image:
            errors.append(
                f"{image_id}: có trong bbox_logo.csv nhưng không có trong duyet_logo.csv"
            )
            continue

        old = labels_by_image[image_id]
        bbox_status = bbox_row["trang_thai_bbox"]
        image_status = old["trang_thai_duyet"]

        if bbox_status == "da_gan_bbox" and image_status != "co_logo_chung_chi":
            errors.append(
                f"{image_id}: bbox nói có logo nhưng duyet_logo.csv là {image_status}"
            )

        if bbox_status == "khong_co_logo" and image_status != "khong_co_logo_chung_chi":
            errors.append(
                f"{image_id}: bbox audit là không logo nhưng duyet_logo.csv là {image_status}"
            )

    for row in label_rows:
        if row["trang_thai_duyet"] in {"chua_duyet", "can_kiem_tra_lai"}:
            errors.append(
                f"{row['ma_anh']}: duyet_logo.csv vẫn còn trạng thái "
                f"{row['trang_thai_duyet']}"
            )

    for label, count in label_counter.items():
        if count < 10:
            warnings.append(
                f"Class '{label}' chỉ có {count} bbox; kết quả đánh giá "
                "sẽ chưa đáng tin cậy."
            )

    return {
        "errors": errors,
        "warnings": warnings,
        "total_boxes": total_boxes,
        "label_counts": label_counter,
    }


def split_products(positive_rows, all_rows):
    """
    Chia theo sản phẩm thay vì chia theo từng ảnh.

    Những sản phẩm chứa class cực hiếm (<=2 sản phẩm có class đó)
    được ưu tiên giữ ở train để model ít nhất được học class đó.
    """
    rng = random.Random(SEED)

    positive_by_product = defaultdict(list)
    for row in positive_rows:
        positive_by_product[row["ma_san_pham"]].append(row)

    class_products = defaultdict(set)

    for product_id, rows in positive_by_product.items():
        for row in rows:
            for box in parse_boxes(row):
                class_products[box["label"]].add(product_id)

    mandatory_train = set()

    for label, products in class_products.items():
        if len(products) <= 2:
            mandatory_train.update(products)

    positive_products = list(positive_by_product.keys())

    remaining = [
        product_id
        for product_id in positive_products
        if product_id not in mandatory_train
    ]

    rng.shuffle(remaining)

    total_positive_images = len(positive_rows)

    targets = {
        "train": total_positive_images * TRAIN_RATIO,
        "val": total_positive_images * VAL_RATIO,
        "test": total_positive_images * TEST_RATIO,
    }

    assignment = {}

    for product_id in mandatory_train:
        assignment[product_id] = "train"

    current = Counter()

    for product_id in mandatory_train:
        current["train"] += len(positive_by_product[product_id])

    for product_id in remaining:
        group_size = len(positive_by_product[product_id])

        deficits = {
            split: targets[split] - current[split]
            for split in ("train", "val", "test")
        }

        # Chọn split đang thiếu nhiều nhất.
        chosen = max(deficits, key=deficits.get)

        assignment[product_id] = chosen
        current[chosen] += group_size

    # Đảm bảo val/test có positive nếu dataset đủ lớn.
    for desired_split in ("val", "test"):
        if any(
            assignment[p] == desired_split
            for p in positive_products
        ):
            continue

        train_candidates = [
            p for p in positive_products
            if assignment[p] == "train" and p not in mandatory_train
        ]

        if train_candidates:
            moved = train_candidates[-1]
            assignment[moved] = desired_split

    # Các sản phẩm chỉ có ảnh negative.
    all_products = sorted({row["ma_san_pham"] for row in all_rows})
    negative_only_products = [
        p for p in all_products if p not in assignment
    ]

    rng.shuffle(negative_only_products)

    for product_id in negative_only_products:
        r = rng.random()

        if r < TRAIN_RATIO:
            assignment[product_id] = "train"
        elif r < TRAIN_RATIO + VAL_RATIO:
            assignment[product_id] = "val"
        else:
            assignment[product_id] = "test"

    return assignment, mandatory_train


def choose_negative_rows(label_rows, product_split, positive_ids):
    """
    Lấy khoảng NEGATIVE_RATIO ảnh không logo cho mỗi ảnh positive,
    riêng từng split.
    """
    rng = random.Random(SEED)

    positives_per_split = Counter()

    for row in label_rows:
        if row["ma_anh"] not in positive_ids:
            continue

        split = product_split[row["ma_san_pham"]]
        positives_per_split[split] += 1

    candidates = defaultdict(list)

    for row in label_rows:
        if row["trang_thai_duyet"] != "khong_co_logo_chung_chi":
            continue

        split = product_split[row["ma_san_pham"]]
        candidates[split].append(row)

    selected = []

    for split in ("train", "val", "test"):
        pool = candidates[split]
        rng.shuffle(pool)

        target = math.ceil(
            positives_per_split[split] * NEGATIVE_RATIO
        )

        selected.extend(pool[: min(target, len(pool))])

    return selected


def clamp(value, low, high):
    return max(low, min(high, value))


def yolo_lines_for_image(row, image_width, image_height):
    lines = []

    boxes = parse_boxes(row)

    for box in boxes:
        label = box["label"]

        x = float(box["x"])
        y = float(box["y"])
        w = float(box["w"])
        h = float(box["h"])

        x1 = clamp(x, 0, image_width)
        y1 = clamp(y, 0, image_height)
        x2 = clamp(x + w, 0, image_width)
        y2 = clamp(y + h, 0, image_height)

        real_w = x2 - x1
        real_h = y2 - y1

        if real_w <= 1 or real_h <= 1:
            raise ValueError(
                f"{row['ma_anh']}: box quá nhỏ sau khi clamp"
            )

        x_center = ((x1 + x2) / 2.0) / image_width
        y_center = ((y1 + y2) / 2.0) / image_height
        width_norm = real_w / image_width
        height_norm = real_h / image_height

        class_id = CLASS_TO_ID[label]

        values = [
            x_center,
            y_center,
            width_norm,
            height_norm,
        ]

        if any(v < 0 or v > 1 for v in values):
            raise ValueError(
                f"{row['ma_anh']}: tọa độ YOLO nằm ngoài [0,1]"
            )

        lines.append(
            f"{class_id} "
            f"{x_center:.6f} "
            f"{y_center:.6f} "
            f"{width_norm:.6f} "
            f"{height_norm:.6f}"
        )

    return lines


def prepare_output(overwrite=False):
    if OUTPUT_DIR.exists():
        if not overwrite:
            raise RuntimeError(
                f"{OUTPUT_DIR} đã tồn tại.\n"
                "Nếu muốn tạo lại, chạy thêm --overwrite"
            )

        shutil.rmtree(OUTPUT_DIR)

    for split in ("train", "val", "test"):
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_one_image(
    source_row,
    split,
    bbox_row=None,
):
    source = resolve_image_path(source_row["duong_dan_anh"])

    if not source.exists():
        raise FileNotFoundError(source)

    suffix = source.suffix.lower()

    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError(
            f"{source_row['ma_anh']}: định dạng ảnh chưa hỗ trợ: {suffix}"
        )

    target_name = f"{source_row['ma_anh']}{suffix}"

    image_target = OUTPUT_DIR / "images" / split / target_name
    label_target = OUTPUT_DIR / "labels" / split / f"{source_row['ma_anh']}.txt"

    shutil.copy2(source, image_target)

    if bbox_row is None:
        # Negative sample -> YOLO label rỗng.
        label_target.write_text("", encoding="utf-8")
        box_count = 0
        labels = []
    else:
        with Image.open(source) as img:
            width, height = img.size

        lines = yolo_lines_for_image(
            bbox_row,
            width,
            height,
        )

        label_target.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

        boxes = parse_boxes(bbox_row)
        box_count = len(boxes)
        labels = [b["label"] for b in boxes]

    return {
        "ma_anh": source_row["ma_anh"],
        "ma_san_pham": source_row["ma_san_pham"],
        "ten_san_pham": source_row["ten_san_pham"],
        "split": split,
        "positive": bbox_row is not None,
        "so_bbox": box_count,
        "labels": "|".join(labels),
        "anh_nguon": str(source.relative_to(PROJECT_ROOT)),
        "anh_yolo": str(image_target.relative_to(PROJECT_ROOT)),
    }


def write_manifest(rows):
    path = OUTPUT_DIR / "split_manifest.csv"

    fields = [
        "ma_anh",
        "ma_san_pham",
        "ten_san_pham",
        "split",
        "positive",
        "so_bbox",
        "labels",
        "anh_nguon",
        "anh_yolo",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_yaml():
    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "",
        "names:",
    ]

    for idx, name in enumerate(CLASS_NAMES):
        lines.append(f"  {idx}: {name}")

    (OUTPUT_DIR / "data.yaml").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def create_summary(
    manifest,
    validation,
    mandatory_train,
):
    summary = {
        "seed": SEED,
        "split_ratio": {
            "train": TRAIN_RATIO,
            "val": VAL_RATIO,
            "test": TEST_RATIO,
        },
        "negative_ratio": NEGATIVE_RATIO,
        "classes": {
            str(idx): name
            for idx, name in enumerate(CLASS_NAMES)
        },
        "bbox_validation": {
            "total_boxes": validation["total_boxes"],
            "label_counts": dict(validation["label_counts"]),
            "warnings": validation["warnings"],
        },
        "mandatory_train_products_due_to_rare_classes": sorted(
            mandatory_train
        ),
        "splits": {},
    }

    for split in ("train", "val", "test"):
        rows = [r for r in manifest if r["split"] == split]

        positive = [r for r in rows if r["positive"]]
        negative = [r for r in rows if not r["positive"]]

        box_counts = Counter()

        for row in positive:
            for label in filter(None, row["labels"].split("|")):
                box_counts[label] += 1

        summary["splits"][split] = {
            "images": len(rows),
            "positive_images": len(positive),
            "negative_images": len(negative),
            "boxes": sum(r["so_bbox"] for r in positive),
            "labels": dict(box_counts),
        }

    (OUTPUT_DIR / "dataset_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return summary


def zip_dataset():
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(
        ZIP_PATH,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        for path in OUTPUT_DIR.rglob("*"):
            if not path.is_file():
                continue

            arcname = Path("yolo_logo") / path.relative_to(OUTPUT_DIR)
            zf.write(path, arcname=str(arcname))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Xóa dataset YOLO cũ và tạo lại.",
    )

    args = parser.parse_args()

    bbox_rows = read_csv(BBOX_CSV)
    label_rows = read_csv(IMAGE_LABEL_CSV)

    print("=" * 70)
    print("1. KIỂM TRA DỮ LIỆU BBOX")
    print("=" * 70)

    validation = validate_bbox_dataset(
        bbox_rows,
        label_rows,
    )

    if validation["errors"]:
        print("\nPHÁT HIỆN LỖI:")
        for error in validation["errors"]:
            print(" -", error)

        raise SystemExit(
            f"\nCó {len(validation['errors'])} lỗi. "
            "Không tạo dataset YOLO."
        )

    print("Bbox hợp lệ.")
    print("Tổng box:", validation["total_boxes"])

    for label in CLASS_NAMES:
        print(
            f"  {label:12s}: "
            f"{validation['label_counts'].get(label, 0)}"
        )

    if validation["warnings"]:
        print("\nCẢNH BÁO:")
        for warning in validation["warnings"]:
            print(" -", warning)

    positive_bbox_rows = [
        row
        for row in bbox_rows
        if row["trang_thai_bbox"] == "da_gan_bbox"
    ]

    positive_ids = {
        row["ma_anh"]
        for row in positive_bbox_rows
    }

    label_by_id = {
        row["ma_anh"]: row
        for row in label_rows
    }

    print("\n" + "=" * 70)
    print("2. CHIA TRAIN / VAL / TEST THEO SẢN PHẨM")
    print("=" * 70)

    product_split, mandatory_train = split_products(
        positive_bbox_rows,
        label_rows,
    )

    negative_rows = choose_negative_rows(
        label_rows,
        product_split,
        positive_ids,
    )

    positive_by_id = {
        row["ma_anh"]: row
        for row in positive_bbox_rows
    }

    prepare_output(args.overwrite)

    manifest = []

    for bbox_row in positive_bbox_rows:
        source_row = label_by_id[bbox_row["ma_anh"]]

        split = product_split[source_row["ma_san_pham"]]

        manifest.append(
            copy_one_image(
                source_row,
                split,
                bbox_row=bbox_row,
            )
        )

    for source_row in negative_rows:
        split = product_split[source_row["ma_san_pham"]]

        manifest.append(
            copy_one_image(
                source_row,
                split,
                bbox_row=None,
            )
        )

    write_manifest(manifest)
    write_yaml()

    summary = create_summary(
        manifest,
        validation,
        mandatory_train,
    )

    zip_dataset()

    print("\n" + "=" * 70)
    print("3. KẾT QUẢ DATASET YOLO")
    print("=" * 70)

    for split in ("train", "val", "test"):
        s = summary["splits"][split]

        print(
            f"{split:5s}: "
            f"{s['images']} ảnh | "
            f"{s['positive_images']} positive | "
            f"{s['negative_images']} negative | "
            f"{s['boxes']} boxes"
        )

    print("\nClass mapping:")

    for idx, name in enumerate(CLASS_NAMES):
        print(f"  {idx}: {name}")

    print("\nDataset:")
    print(OUTPUT_DIR)

    print("\nZIP để đưa lên Google Drive/Colab:")
    print(ZIP_PATH)

    print("\nHOÀN TẤT.")
    print(
        "Chưa train model. Bước tiếp theo là mở Google Colab "
        "và dùng yolo_logo_dataset.zip."
    )


if __name__ == "__main__":
    main()
