from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "yolo_logo_binary"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "yolo_logo_run3"
DEFAULT_ZIP = PROJECT_ROOT / "yolo_logo_run3_dataset.zip"

SPLITS = ("train", "val", "test")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def read_yolo_boxes(label_path: Path, image_w: int, image_h: int):
    boxes = []
    if not label_path.exists():
        return boxes

    raw = label_path.read_text(encoding="utf-8").strip()
    if not raw:
        return boxes

    for line_no, line in enumerate(raw.splitlines(), start=1):
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{label_path}: dòng {line_no} không đúng YOLO format")

        class_id, xc, yc, w, h = parts
        class_id = int(class_id)
        xc, yc, w, h = map(float, (xc, yc, w, h))

        if class_id != 0:
            raise ValueError(
                f"{label_path}: Run 3 chỉ dùng binary class 0, gặp class {class_id}"
            )

        x1 = (xc - w / 2.0) * image_w
        y1 = (yc - h / 2.0) * image_h
        x2 = (xc + w / 2.0) * image_w
        y2 = (yc + h / 2.0) * image_h

        boxes.append([x1, y1, x2, y2])

    return boxes


def clamp(v, low, high):
    return max(low, min(high, v))


def context_crop(box, image_w, image_h, scale=3.0, min_side=128):
    x1, y1, x2, y2 = box
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    crop_w = min(float(image_w), max(float(min_side), bw * scale))
    crop_h = min(float(image_h), max(float(min_side), bh * scale))

    left = cx - crop_w / 2.0
    top = cy - crop_h / 2.0

    left = clamp(left, 0.0, image_w - crop_w)
    top = clamp(top, 0.0, image_h - crop_h)

    right = left + crop_w
    bottom = top + crop_h

    return [left, top, right, bottom]


def intersection_fraction(box, crop):
    x1, y1, x2, y2 = box
    cx1, cy1, cx2, cy2 = crop

    ix1 = max(x1, cx1)
    iy1 = max(y1, cy1)
    ix2 = min(x2, cx2)
    iy2 = min(y2, cy2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih

    area = max(1e-9, (x2 - x1) * (y2 - y1))
    return inter / area


def transform_boxes_to_crop(boxes, crop, min_visible=0.5):
    cx1, cy1, cx2, cy2 = crop
    crop_w = cx2 - cx1
    crop_h = cy2 - cy1

    lines = []

    for box in boxes:
        if intersection_fraction(box, crop) < min_visible:
            continue

        x1, y1, x2, y2 = box

        nx1 = clamp(x1, cx1, cx2) - cx1
        ny1 = clamp(y1, cy1, cy2) - cy1
        nx2 = clamp(x2, cx1, cx2) - cx1
        ny2 = clamp(y2, cy1, cy2) - cy1

        bw = nx2 - nx1
        bh = ny2 - ny1

        if bw <= 1 or bh <= 1:
            continue

        xc = ((nx1 + nx2) / 2.0) / crop_w
        yc = ((ny1 + ny2) / 2.0) / crop_h
        nw = bw / crop_w
        nh = bh / crop_h

        vals = [xc, yc, nw, nh]
        if any(v < 0.0 or v > 1.0 for v in vals):
            raise ValueError("Tọa độ crop YOLO nằm ngoài [0,1]")

        lines.append(f"0 {xc:.6f} {yc:.6f} {nw:.6f} {nh:.6f}")

    return lines


def ensure_source(source_dir: Path):
    required = [source_dir / "data.yaml"]
    for split in SPLITS:
        required.extend([
            source_dir / "images" / split,
            source_dir / "labels" / split,
        ])

    missing = [p for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Dataset binary nguồn chưa đầy đủ:\n" +
            "\n".join(f" - {p}" for p in missing)
        )


def prepare_output(output_dir: Path, overwrite: bool):
    if output_dir.exists():
        if not overwrite:
            raise RuntimeError(
                f"{output_dir} đã tồn tại. Dùng --overwrite để tạo lại."
            )
        shutil.rmtree(output_dir)

    for split in SPLITS:
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_original_dataset(source_dir: Path, output_dir: Path):
    for split in SPLITS:
        src_images = source_dir / "images" / split
        src_labels = source_dir / "labels" / split
        dst_images = output_dir / "images" / split
        dst_labels = output_dir / "labels" / split

        for p in src_images.iterdir():
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                shutil.copy2(p, dst_images / p.name)

        for p in src_labels.glob("*.txt"):
            shutil.copy2(p, dst_labels / p.name)


def add_positive_crops(
    source_dir: Path,
    output_dir: Path,
    crop_scales=(3.0, 5.0),
    min_crop_side=128,
):
    src_images = source_dir / "images" / "train"
    src_labels = source_dir / "labels" / "train"
    dst_images = output_dir / "images" / "train"
    dst_labels = output_dir / "labels" / "train"

    added_images = 0
    added_boxes = 0
    manifest = []

    for image_path in sorted(src_images.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTS:
            continue

        label_path = src_labels / f"{image_path.stem}.txt"
        raw = label_path.read_text(encoding="utf-8").strip() if label_path.exists() else ""
        if not raw:
            continue

        with Image.open(image_path) as im:
            im = im.convert("RGB")
            image_w, image_h = im.size
            boxes = read_yolo_boxes(label_path, image_w, image_h)

            for target_idx, target_box in enumerate(boxes):
                for scale in crop_scales:
                    crop = context_crop(
                        target_box,
                        image_w,
                        image_h,
                        scale=scale,
                        min_side=min_crop_side,
                    )

                    label_lines = transform_boxes_to_crop(
                        boxes,
                        crop,
                        min_visible=0.5,
                    )

                    if not label_lines:
                        continue

                    left, top, right, bottom = crop
                    crop_img = im.crop((
                        int(round(left)),
                        int(round(top)),
                        int(round(right)),
                        int(round(bottom)),
                    ))

                    suffix_tag = str(scale).replace(".", "p")
                    name = (
                        f"zoom_{image_path.stem}_obj{target_idx + 1}"
                        f"_s{suffix_tag}.jpg"
                    )

                    crop_img.save(
                        dst_images / name,
                        format="JPEG",
                        quality=95,
                        subsampling=0,
                    )
                    (dst_labels / f"{Path(name).stem}.txt").write_text(
                        "\n".join(label_lines) + "\n",
                        encoding="utf-8",
                    )

                    added_images += 1
                    added_boxes += len(label_lines)

                    manifest.append({
                        "aug_image": name,
                        "source_image": image_path.name,
                        "target_box_index": target_idx,
                        "scale": scale,
                        "boxes_in_crop": len(label_lines),
                    })

    manifest_path = output_dir / "positive_crop_manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "aug_image",
                "source_image",
                "target_box_index",
                "scale",
                "boxes_in_crop",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest)

    return added_images, added_boxes


def mine_hard_negatives(
    source_dir: Path,
    output_dir: Path,
    model_path: Path | None,
    conf_threshold=0.20,
    max_total=80,
    per_image=2,
    context_scale=2.5,
    min_crop_side=160,
    imgsz=960,
):
    if model_path is None:
        print("Bỏ qua hard-negative mining vì chưa truyền --run2-model.")
        return 0

    if not model_path.exists():
        raise FileNotFoundError(f"Không tìm thấy model Run 2: {model_path}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Cần cài ultralytics để mine hard negatives: pip install ultralytics"
        ) from exc

    train_images = source_dir / "images" / "train"
    train_labels = source_dir / "labels" / "train"
    dst_images = output_dir / "images" / "train"
    dst_labels = output_dir / "labels" / "train"

    negative_images = []

    for image_path in sorted(train_images.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTS:
            continue

        label_path = train_labels / f"{image_path.stem}.txt"
        raw = label_path.read_text(encoding="utf-8").strip() if label_path.exists() else ""

        if not raw:
            negative_images.append(image_path)

    if not negative_images:
        return 0

    print(
        f"Mine hard negatives từ {len(negative_images)} ảnh train negative "
        f"với conf >= {conf_threshold}..."
    )

    model = YOLO(str(model_path))
    results = model.predict(
        source=[str(p) for p in negative_images],
        imgsz=imgsz,
        conf=conf_threshold,
        iou=0.7,
        verbose=False,
        save=False,
    )

    candidates = []

    for image_path, result in zip(negative_images, results):
        if result.boxes is None or len(result.boxes) == 0:
            continue

        boxes = result.boxes.xyxy.cpu().numpy().tolist()
        confs = result.boxes.conf.cpu().numpy().tolist()

        ranked = sorted(
            zip(boxes, confs),
            key=lambda x: x[1],
            reverse=True,
        )[:per_image]

        for box, conf in ranked:
            candidates.append((conf, image_path, box))

    candidates.sort(key=lambda x: x[0], reverse=True)
    candidates = candidates[:max_total]

    manifest = []
    added = 0

    for idx, (conf, image_path, pred_box) in enumerate(candidates, start=1):
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            image_w, image_h = im.size

            crop = context_crop(
                pred_box,
                image_w,
                image_h,
                scale=context_scale,
                min_side=min_crop_side,
            )

            left, top, right, bottom = crop
            crop_img = im.crop((
                int(round(left)),
                int(round(top)),
                int(round(right)),
                int(round(bottom)),
            ))

            name = f"hardneg_{idx:04d}_{image_path.stem}.jpg"

            crop_img.save(
                dst_images / name,
                format="JPEG",
                quality=95,
                subsampling=0,
            )
            (dst_labels / f"{Path(name).stem}.txt").write_text(
                "",
                encoding="utf-8",
            )

            manifest.append({
                "hard_negative_image": name,
                "source_image": image_path.name,
                "run2_confidence": round(float(conf), 6),
                "pred_x1": round(float(pred_box[0]), 2),
                "pred_y1": round(float(pred_box[1]), 2),
                "pred_x2": round(float(pred_box[2]), 2),
                "pred_y2": round(float(pred_box[3]), 2),
            })
            added += 1

    manifest_path = output_dir / "hard_negative_manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "hard_negative_image",
                "source_image",
                "run2_confidence",
                "pred_x1",
                "pred_y1",
                "pred_x2",
                "pred_y2",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest)

    return added


def count_split(output_dir: Path, split: str):
    image_dir = output_dir / "images" / split
    label_dir = output_dir / "labels" / split

    images = [
        p for p in image_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]

    positives = 0
    negatives = 0
    boxes = 0

    for image_path in images:
        label_path = label_dir / f"{image_path.stem}.txt"
        if not label_path.exists():
            raise RuntimeError(f"Thiếu label: {label_path}")

        raw = label_path.read_text(encoding="utf-8").strip()
        if raw:
            positives += 1
            boxes += len([line for line in raw.splitlines() if line.strip()])
        else:
            negatives += 1

    return {
        "images": len(images),
        "positive_images": positives,
        "negative_images": negatives,
        "boxes": boxes,
    }


def write_yaml(output_dir: Path):
    (output_dir / "data.yaml").write_text(
        "path: .\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "\n"
        "names:\n"
        "  0: logo_chung_chi\n",
        encoding="utf-8",
    )


def zip_dataset(output_dir: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        for p in output_dir.rglob("*"):
            if p.is_file():
                arcname = Path(output_dir.name) / p.relative_to(output_dir)
                zf.write(p, arcname=str(arcname))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Tạo dataset Run 3: giữ nguyên val/test, "
            "augment positive train bằng crop/zoom và tùy chọn hard-negative mining."
        )
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zip-path", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--run2-model", type=Path, default=None)
    parser.add_argument("--crop-scales", nargs="+", type=float, default=[3.0, 5.0])
    parser.add_argument("--min-crop-side", type=int, default=128)
    parser.add_argument("--hard-negative-conf", type=float, default=0.20)
    parser.add_argument("--max-hard-negatives", type=int, default=80)
    parser.add_argument("--hard-negatives-per-image", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source_dir = args.source.resolve()
    output_dir = args.output.resolve()
    zip_path = args.zip_path.resolve()
    model_path = args.run2_model.resolve() if args.run2_model else None

    ensure_source(source_dir)
    prepare_output(output_dir, args.overwrite)

    print("=" * 72)
    print("1. COPY DATASET GỐC — GIỮ NGUYÊN TRAIN / VAL / TEST")
    print("=" * 72)
    copy_original_dataset(source_dir, output_dir)

    print("\n" + "=" * 72)
    print("2. THÊM POSITIVE CROP / ZOOM CHỈ VÀO TRAIN")
    print("=" * 72)
    crop_images, crop_boxes = add_positive_crops(
        source_dir,
        output_dir,
        crop_scales=tuple(args.crop_scales),
        min_crop_side=args.min_crop_side,
    )
    print(f"Đã thêm {crop_images} ảnh crop positive, {crop_boxes} bbox.")

    print("\n" + "=" * 72)
    print("3. HARD-NEGATIVE MINING CHỈ TỪ TRAIN NEGATIVE")
    print("=" * 72)
    hardneg_count = mine_hard_negatives(
        source_dir,
        output_dir,
        model_path=model_path,
        conf_threshold=args.hard_negative_conf,
        max_total=args.max_hard_negatives,
        per_image=args.hard_negatives_per_image,
        imgsz=960,
    )
    print(f"Đã thêm {hardneg_count} hard-negative crop.")

    write_yaml(output_dir)

    summary = {
        "source_dataset": str(source_dir),
        "run2_model_for_hard_negative_mining": str(model_path) if model_path else None,
        "augmentation": {
            "positive_crop_scales": args.crop_scales,
            "positive_crop_images_added": crop_images,
            "positive_crop_boxes_added": crop_boxes,
            "hard_negative_conf": args.hard_negative_conf,
            "hard_negative_images_added": hardneg_count,
        },
        "splits": {},
    }

    for split in SPLITS:
        summary["splits"][split] = count_split(output_dir, split)

    (output_dir / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    zip_dataset(output_dir, zip_path)

    print("\n" + "=" * 72)
    print("4. KẾT QUẢ RUN 3 DATASET")
    print("=" * 72)

    for split in SPLITS:
        s = summary["splits"][split]
        print(
            f"{split:5s}: {s['images']} ảnh | "
            f"{s['positive_images']} positive | "
            f"{s['negative_images']} negative | "
            f"{s['boxes']} boxes"
        )

    print("\nVal/test phải giữ nguyên Run 2:")
    print("  val : 45 ảnh | 15 positive | 30 negative | 15 boxes")
    print("  test: 39 ảnh | 13 positive | 26 negative | 17 boxes")

    print("\nDataset Run 3:")
    print(output_dir)
    print("\nZIP:")
    print(zip_path)
    print("\nHOÀN TẤT.")


if __name__ == "__main__":
    main()
