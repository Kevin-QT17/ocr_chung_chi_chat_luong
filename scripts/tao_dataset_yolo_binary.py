from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "yolo_logo"
OUTPUT_DIR = PROJECT_ROOT / "data" / "yolo_logo_binary"
ZIP_PATH = PROJECT_ROOT / "yolo_logo_binary_dataset.zip"

SPLITS = ("train", "val", "test")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def ensure_source_exists():
    required = [
        SOURCE_DIR / "data.yaml",
        SOURCE_DIR / "split_manifest.csv",
    ]
    for split in SPLITS:
        required += [
            SOURCE_DIR / "images" / split,
            SOURCE_DIR / "labels" / split,
        ]

    missing = [p for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Dataset multiclass chưa đầy đủ. Thiếu:\n"
            + "\n".join(f" - {p}" for p in missing)
        )


def prepare_output(overwrite=False):
    if OUTPUT_DIR.exists():
        if not overwrite:
            raise RuntimeError(
                f"{OUTPUT_DIR} đã tồn tại. Chạy thêm --overwrite để tạo lại."
            )
        shutil.rmtree(OUTPUT_DIR)

    for split in SPLITS:
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_images():
    counts = Counter()

    for split in SPLITS:
        src_dir = SOURCE_DIR / "images" / split
        dst_dir = OUTPUT_DIR / "images" / split

        for src in sorted(src_dir.iterdir()):
            if src.is_file() and src.suffix.lower() in IMAGE_EXTENSIONS:
                shutil.copy2(src, dst_dir / src.name)
                counts[split] += 1

    return counts


def convert_label_file(src, dst):
    raw = src.read_text(encoding="utf-8").strip()

    if not raw:
        dst.write_text("", encoding="utf-8")
        return 0

    output_lines = []

    for line_no, line in enumerate(raw.splitlines(), 1):
        parts = line.strip().split()

        if len(parts) != 5:
            raise ValueError(
                f"{src}: dòng {line_no} không đúng YOLO format: {line!r}"
            )

        try:
            old_class = int(parts[0])
            coords = [float(v) for v in parts[1:]]
        except ValueError as exc:
            raise ValueError(
                f"{src}: dòng {line_no} có giá trị không hợp lệ"
            ) from exc

        if old_class < 0:
            raise ValueError(f"{src}: dòng {line_no} có class ID âm")

        if any(v < 0.0 or v > 1.0 for v in coords):
            raise ValueError(
                f"{src}: dòng {line_no} có tọa độ ngoài [0,1]"
            )

        output_lines.append(
            "0 " + " ".join(f"{value:.6f}" for value in coords)
        )

    dst.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return len(output_lines)


def convert_labels():
    stats = {}

    for split in SPLITS:
        src_dir = SOURCE_DIR / "labels" / split
        dst_dir = OUTPUT_DIR / "labels" / split

        label_files = 0
        positive_images = 0
        negative_images = 0
        boxes = 0

        for src in sorted(src_dir.glob("*.txt")):
            count = convert_label_file(src, dst_dir / src.name)

            label_files += 1
            boxes += count

            if count > 0:
                positive_images += 1
            else:
                negative_images += 1

        stats[split] = {
            "label_files": label_files,
            "positive_images": positive_images,
            "negative_images": negative_images,
            "boxes": boxes,
        }

    return stats


def write_data_yaml():
    content = (
        "path: .\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "\n"
        "names:\n"
        "  0: logo_chung_chi\n"
    )
    (OUTPUT_DIR / "data.yaml").write_text(content, encoding="utf-8")


def copy_manifest():
    src = SOURCE_DIR / "split_manifest.csv"
    dst = OUTPUT_DIR / "split_manifest.csv"

    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    if "binary_class" not in fields:
        fields.append("binary_class")

    for row in rows:
        is_positive = str(row.get("positive", "")).lower() in {
            "true", "1", "yes"
        }
        row["binary_class"] = "logo_chung_chi" if is_positive else ""

    with dst.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def validate_pairs(image_counts, label_stats):
    errors = []

    for split in SPLITS:
        image_stems = {
            p.stem
            for p in (OUTPUT_DIR / "images" / split).iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        }
        label_stems = {
            p.stem
            for p in (OUTPUT_DIR / "labels" / split).glob("*.txt")
            if p.is_file()
        }

        if image_stems != label_stems:
            errors.append(
                f"{split}: tập ảnh và tập label không khớp"
            )

        if image_counts[split] != label_stats[split]["label_files"]:
            errors.append(
                f"{split}: số ảnh khác số label"
            )

    if errors:
        raise RuntimeError(
            "Dataset binary không nhất quán:\n - "
            + "\n - ".join(errors)
        )


def write_summary(image_counts, label_stats):
    summary = {
        "task": "object_detection_binary",
        "class_names": {"0": "logo_chung_chi"},
        "source_dataset": str(SOURCE_DIR.relative_to(PROJECT_ROOT)),
        "splits": {},
    }

    total_images = 0
    total_positive = 0
    total_negative = 0
    total_boxes = 0

    for split in SPLITS:
        item = {
            "images": image_counts[split],
            "positive_images": label_stats[split]["positive_images"],
            "negative_images": label_stats[split]["negative_images"],
            "boxes": label_stats[split]["boxes"],
        }
        summary["splits"][split] = item
        total_images += item["images"]
        total_positive += item["positive_images"]
        total_negative += item["negative_images"]
        total_boxes += item["boxes"]

    summary["totals"] = {
        "images": total_images,
        "positive_images": total_positive,
        "negative_images": total_negative,
        "boxes": total_boxes,
    }

    (OUTPUT_DIR / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
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
            if path.is_file():
                arcname = Path("yolo_logo_binary") / path.relative_to(OUTPUT_DIR)
                zf.write(path, arcname=str(arcname))


def main():
    parser = argparse.ArgumentParser(
        description="Tạo dataset YOLO binary 1 class từ dataset multiclass."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Xóa dataset binary cũ và tạo lại.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("1. KIỂM TRA DATASET MULTICLASS NGUỒN")
    print("=" * 72)

    ensure_source_exists()
    print("Nguồn hợp lệ:")
    print(SOURCE_DIR)

    print("\n" + "=" * 72)
    print("2. TẠO DATASET YOLO BINARY")
    print("=" * 72)

    prepare_output(args.overwrite)
    image_counts = copy_images()
    label_stats = convert_labels()

    write_data_yaml()
    copy_manifest()
    validate_pairs(image_counts, label_stats)
    summary = write_summary(image_counts, label_stats)
    zip_dataset()

    print("\n" + "=" * 72)
    print("3. KẾT QUẢ")
    print("=" * 72)

    for split in SPLITS:
        item = summary["splits"][split]
        print(
            f"{split:5s}: "
            f"{item['images']} ảnh | "
            f"{item['positive_images']} positive | "
            f"{item['negative_images']} negative | "
            f"{item['boxes']} boxes"
        )

    totals = summary["totals"]

    print("\nTổng:")
    print(
        f"{totals['images']} ảnh | "
        f"{totals['positive_images']} positive | "
        f"{totals['negative_images']} negative | "
        f"{totals['boxes']} boxes"
    )

    print("\nClass mapping:")
    print("  0: logo_chung_chi")

    print("\nDataset binary:")
    print(OUTPUT_DIR)

    print("\nZIP để đưa lên Google Drive/Colab:")
    print(ZIP_PATH)

    print("\nHOÀN TẤT.")
    print("Dataset binary đã sẵn sàng. Chưa train model ở bước này.")


if __name__ == "__main__":
    main()
