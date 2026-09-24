from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "yolo_logo"
OUTPUT_DIR = PROJECT_ROOT / "data" / "yolo_logo_multiclass_aug"

SPLITS = ("train", "val", "test")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

CLASS_NAMES = {
    0: "haccp",
    1: "fda",
    2: "gmp",
    3: "iso_22000",
    4: "ocop",
    5: "khac",
}

# Mục tiêu augmentation có kiểm soát.
# Không cố biến 2 FDA thành hàng trăm mẫu vì đó vẫn chỉ là biến thể của 2 ảnh gốc.
TARGET_BOX_COUNTS = {
    0: 16,  # haccp
    1: 16,  # fda
    2: 24,  # gmp
    3: 16,  # iso_22000
    4: 36,  # ocop
    5: 40,  # khac: không cố tăng thêm vì đã nhiều và rất không đồng nhất
}

SEED = 42
MAX_ATTEMPTS_PER_CLASS = 200


def read_label_file(path: Path):
    rows = []
    raw = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not raw:
        return rows

    for line_no, line in enumerate(raw.splitlines(), start=1):
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path}: dòng {line_no} không đúng YOLO format")

        class_id = int(parts[0])
        xc, yc, w, h = map(float, parts[1:])
        rows.append([class_id, xc, yc, w, h])

    return rows


def write_label_file(path: Path, labels):
    lines = []
    for class_id, xc, yc, w, h in labels:
        lines.append(
            f"{int(class_id)} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def ensure_source():
    required = [SOURCE_DIR / "data.yaml"]

    for split in SPLITS:
        required += [
            SOURCE_DIR / "images" / split,
            SOURCE_DIR / "labels" / split,
        ]

    missing = [p for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Thiếu dataset multiclass nguồn:\n"
            + "\n".join(f" - {p}" for p in missing)
        )


def prepare_output(overwrite: bool):
    if OUTPUT_DIR.exists():
        if not overwrite:
            raise RuntimeError(
                f"{OUTPUT_DIR} đã tồn tại. Chạy thêm --overwrite để tạo lại."
            )
        shutil.rmtree(OUTPUT_DIR)

    for split in SPLITS:
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_original():
    for split in SPLITS:
        for p in (SOURCE_DIR / "images" / split).iterdir():
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                shutil.copy2(p, OUTPUT_DIR / "images" / split / p.name)

        for p in (SOURCE_DIR / "labels" / split).glob("*.txt"):
            shutil.copy2(p, OUTPUT_DIR / "labels" / split / p.name)


def get_train_records():
    records = []

    image_dir = SOURCE_DIR / "images" / "train"
    label_dir = SOURCE_DIR / "labels" / "train"

    for image_path in sorted(image_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTS:
            continue

        label_path = label_dir / f"{image_path.stem}.txt"
        labels = read_label_file(label_path)

        if not labels:
            continue

        records.append({
            "image_path": image_path,
            "label_path": label_path,
            "labels": labels,
        })

    return records


def count_boxes(records):
    c = Counter()
    for r in records:
        for class_id, *_ in r["labels"]:
            c[class_id] += 1
    return c


def yolo_to_xyxy(label, iw, ih):
    class_id, xc, yc, w, h = label
    x1 = (xc - w / 2.0) * iw
    y1 = (yc - h / 2.0) * ih
    x2 = (xc + w / 2.0) * iw
    y2 = (yc + h / 2.0) * ih
    return class_id, x1, y1, x2, y2


def xyxy_to_yolo(class_id, x1, y1, x2, y2, iw, ih):
    x1 = max(0.0, min(iw, x1))
    y1 = max(0.0, min(ih, y1))
    x2 = max(0.0, min(iw, x2))
    y2 = max(0.0, min(ih, y2))

    if x2 - x1 <= 2 or y2 - y1 <= 2:
        return None

    xc = ((x1 + x2) / 2.0) / iw
    yc = ((y1 + y2) / 2.0) / ih
    w = (x2 - x1) / iw
    h = (y2 - y1) / ih

    if any(v < 0.0 or v > 1.0 for v in (xc, yc, w, h)):
        return None

    return [class_id, xc, yc, w, h]


def mild_photometric(img: Image.Image, rng: random.Random):
    # Không đổi màu quá mạnh vì màu sắc có thể là đặc trưng logo.
    brightness = rng.uniform(0.82, 1.18)
    contrast = rng.uniform(0.82, 1.18)
    color = rng.uniform(0.88, 1.12)
    sharpness = rng.uniform(0.85, 1.25)

    img = ImageEnhance.Brightness(img).enhance(brightness)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(color)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)

    if rng.random() < 0.20:
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 1.0)))

    return img


def rotate_with_boxes(img: Image.Image, labels, angle_deg: float):
    iw, ih = img.size
    cx = iw / 2.0
    cy = ih / 2.0
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def rotate_point(x, y):
        dx = x - cx
        dy = y - cy
        rx = dx * cos_a - dy * sin_a + cx
        ry = dx * sin_a + dy * cos_a + cy
        return rx, ry

    new_labels = []

    for label in labels:
        class_id, x1, y1, x2, y2 = yolo_to_xyxy(label, iw, ih)

        corners = [
            rotate_point(x1, y1),
            rotate_point(x2, y1),
            rotate_point(x2, y2),
            rotate_point(x1, y2),
        ]

        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]

        converted = xyxy_to_yolo(
            class_id,
            min(xs),
            min(ys),
            max(xs),
            max(ys),
            iw,
            ih,
        )

        if converted is not None:
            new_labels.append(converted)

    rotated = img.rotate(
        angle_deg,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=(255, 255, 255),
    )

    return rotated, new_labels


def context_zoom(img: Image.Image, labels, target_class: int, rng: random.Random):
    """
    Crop quanh một object thuộc target_class nhưng giữ context rộng.
    Sau đó resize lại về kích thước gốc.
    """
    iw, ih = img.size

    target_indices = [
        i for i, x in enumerate(labels) if int(x[0]) == target_class
    ]

    if not target_indices:
        return img, labels

    idx = rng.choice(target_indices)
    class_id, x1, y1, x2, y2 = yolo_to_xyxy(labels[idx], iw, ih)

    bw = x2 - x1
    bh = y2 - y1
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    # Context rộng 4–8 lần bbox, tránh crop quá sát như Run 3 binary.
    scale = rng.uniform(4.0, 8.0)
    crop_w = min(iw, max(256.0, bw * scale))
    crop_h = min(ih, max(256.0, bh * scale))

    left = max(0.0, min(iw - crop_w, cx - crop_w / 2.0))
    top = max(0.0, min(ih - crop_h, cy - crop_h / 2.0))
    right = left + crop_w
    bottom = top + crop_h

    out_labels = []

    for label in labels:
        cid, bx1, by1, bx2, by2 = yolo_to_xyxy(label, iw, ih)

        ix1 = max(bx1, left)
        iy1 = max(by1, top)
        ix2 = min(bx2, right)
        iy2 = min(by2, bottom)

        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        area = max(1e-9, (bx2 - bx1) * (by2 - by1))
        visible = inter / area

        if visible < 0.70:
            continue

        nx1 = (ix1 - left) * iw / crop_w
        ny1 = (iy1 - top) * ih / crop_h
        nx2 = (ix2 - left) * iw / crop_w
        ny2 = (iy2 - top) * ih / crop_h

        converted = xyxy_to_yolo(
            cid,
            nx1,
            ny1,
            nx2,
            ny2,
            iw,
            ih,
        )
        if converted is not None:
            out_labels.append(converted)

    crop = img.crop((
        int(round(left)),
        int(round(top)),
        int(round(right)),
        int(round(bottom)),
    )).resize((iw, ih), Image.Resampling.LANCZOS)

    return crop, out_labels


def jpeg_roundtrip(img: Image.Image, rng: random.Random):
    quality = rng.randint(65, 95)
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=quality, subsampling=0)
    bio.seek(0)
    return Image.open(bio).convert("RGB")


def augment_record(record, target_class: int, rng: random.Random):
    img = Image.open(record["image_path"]).convert("RGB")
    labels = [list(x) for x in record["labels"]]

    # 60% số biến thể có context zoom để giúp logo nhỏ.
    if rng.random() < 0.60:
        img, labels = context_zoom(img, labels, target_class, rng)

    if not any(int(x[0]) == target_class for x in labels):
        return None

    # Rotation nhẹ, không flip ngang vì logo/text bị mirror sẽ phi thực tế.
    if rng.random() < 0.70:
        angle = rng.uniform(-7.0, 7.0)
        img, labels = rotate_with_boxes(img, labels, angle)

    if not any(int(x[0]) == target_class for x in labels):
        return None

    img = mild_photometric(img, rng)

    if rng.random() < 0.35:
        img = jpeg_roundtrip(img, rng)

    return img, labels


def augment_balanced(records):
    rng = random.Random(SEED)

    by_class = defaultdict(list)
    for record in records:
        present = {int(x[0]) for x in record["labels"]}
        for class_id in present:
            by_class[class_id].append(record)

    current_counts = count_boxes(records)
    generated_counts = Counter()

    manifest_rows = []

    for class_id in range(len(CLASS_NAMES)):
        target = TARGET_BOX_COUNTS[class_id]
        current = current_counts[class_id]

        print(
            f"{CLASS_NAMES[class_id]:12s}: "
            f"train gốc={current}, mục tiêu={target}"
        )

        if current >= target:
            continue

        sources = by_class[class_id]
        if not sources:
            print("  -> Không có ảnh nguồn, bỏ qua.")
            continue

        attempts = 0
        generated_index = 1

        while (
            current_counts[class_id] + generated_counts[class_id] < target
            and attempts < MAX_ATTEMPTS_PER_CLASS
        ):
            attempts += 1

            source = rng.choice(sources)
            augmented = augment_record(source, class_id, rng)

            if augmented is None:
                continue

            img, labels = augmented

            # Đếm số box class mục tiêu thực sự còn lại.
            gained = sum(1 for x in labels if int(x[0]) == class_id)
            if gained <= 0:
                continue

            filename = (
                f"aug_{CLASS_NAMES[class_id]}_"
                f"{generated_index:04d}_{source['image_path'].stem}.jpg"
            )
            image_out = OUTPUT_DIR / "images" / "train" / filename
            label_out = OUTPUT_DIR / "labels" / "train" / f"{Path(filename).stem}.txt"

            img.save(image_out, format="JPEG", quality=95, subsampling=0)
            write_label_file(label_out, labels)

            for cid, *_ in labels:
                generated_counts[int(cid)] += 1

            manifest_rows.append({
                "aug_image": filename,
                "focus_class": CLASS_NAMES[class_id],
                "source_image": source["image_path"].name,
                "total_boxes": len(labels),
                "focus_boxes": gained,
            })

            generated_index += 1

    with (OUTPUT_DIR / "augmentation_manifest.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "aug_image",
                "focus_class",
                "source_image",
                "total_boxes",
                "focus_boxes",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    return current_counts, generated_counts, len(manifest_rows)


def split_stats(split):
    image_dir = OUTPUT_DIR / "images" / split
    label_dir = OUTPUT_DIR / "labels" / split

    stats = Counter()
    images = 0
    positive = 0
    negative = 0

    for img in image_dir.iterdir():
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue

        images += 1
        labels = read_label_file(label_dir / f"{img.stem}.txt")

        if labels:
            positive += 1
            for cid, *_ in labels:
                stats[int(cid)] += 1
        else:
            negative += 1

    return {
        "images": images,
        "positive_images": positive,
        "negative_images": negative,
        "box_counts": {
            CLASS_NAMES[i]: stats[i]
            for i in range(len(CLASS_NAMES))
        },
    }


def write_yaml():
    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "",
        "names:",
    ]

    for class_id, name in CLASS_NAMES.items():
        lines.append(f"  {class_id}: {name}")

    (OUTPUT_DIR / "data.yaml").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    ensure_source()
    prepare_output(args.overwrite)
    copy_original()

    records = get_train_records()

    print("=" * 72)
    print("TẠO DATASET MULTICLASS AUGMENT CÂN BẰNG")
    print("=" * 72)

    original_counts, generated_counts, generated_images = augment_balanced(records)

    write_yaml()

    summary = {
        "seed": SEED,
        "classes": CLASS_NAMES,
        "target_box_counts": TARGET_BOX_COUNTS,
        "original_train_box_counts": {
            CLASS_NAMES[i]: original_counts[i]
            for i in range(len(CLASS_NAMES))
        },
        "generated_box_counts": {
            CLASS_NAMES[i]: generated_counts[i]
            for i in range(len(CLASS_NAMES))
        },
        "generated_images": generated_images,
        "splits": {
            split: split_stats(split)
            for split in SPLITS
        },
        "notes": [
            "Chỉ augment train; val/test giữ nguyên.",
            "Không horizontal flip để tránh logo/text bị mirror.",
            "Augmentation chỉ tăng biến thiên hình học/ánh sáng; không thay thế dữ liệu thật.",
            "Class khac không tăng thêm chủ động vì rất không đồng nhất về ngữ nghĩa.",
        ],
    }

    (OUTPUT_DIR / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("KẾT QUẢ")
    print("=" * 72)

    for split in SPLITS:
        s = summary["splits"][split]
        print(
            f"{split:5s}: {s['images']} ảnh | "
            f"{s['positive_images']} positive | "
            f"{s['negative_images']} negative"
        )
        print("       boxes:", s["box_counts"])

    print("\nẢnh augment mới:", generated_images)
    print("Dataset:", OUTPUT_DIR)
    print(
        "\nLưu ý: FDA/ISO/HACCP vẫn chỉ có rất ít ảnh gốc. "
        "Augmentation giúp cân bằng và tăng robustness, "
        "nhưng không tạo ra semantic diversity mới."
    )


if __name__ == "__main__":
    main()
