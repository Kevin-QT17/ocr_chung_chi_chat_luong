from pathlib import Path
from collections import Counter
from PIL import Image
import argparse
import csv
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent

SOURCE = ROOT / "data" / "yolo_logo"
OUTPUT = ROOT / "data" / "logo_classifier_raw"
ZIP_OUT = ROOT / "logo_classifier_raw.zip"

SPLITS = ("train", "val", "test")

CLASSES = {
    0: "haccp",
    1: "fda",
    2: "gmp",
    3: "iso_22000",
    4: "ocop",
    5: "khac",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def read_labels(path):
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8").strip()

    if not text:
        return []

    result = []

    for line in text.splitlines():
        parts = line.split()

        if len(parts) != 5:
            raise ValueError(f"Sai YOLO format: {path}")

        class_id = int(parts[0])
        xc, yc, w, h = map(float, parts[1:])

        result.append((class_id, xc, yc, w, h))

    return result


def crop_coords(xc, yc, w, h, image_w, image_h, padding=0.08):
    x1 = (xc - w / 2) * image_w
    y1 = (yc - h / 2) * image_h
    x2 = (xc + w / 2) * image_w
    y2 = (yc + h / 2) * image_h

    bw = x2 - x1
    bh = y2 - y1

    x1 -= bw * padding
    y1 -= bh * padding
    x2 += bw * padding
    y2 += bh * padding

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(image_w, x2)
    y2 = min(image_h, y2)

    return x1, y1, x2, y2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not SOURCE.exists():
        raise FileNotFoundError(
            f"Không tìm thấy dataset nguồn: {SOURCE}"
        )

    if OUTPUT.exists():
        if not args.overwrite:
            raise RuntimeError(
                f"{OUTPUT} đã tồn tại. "
                "Dùng --overwrite nếu muốn tạo lại."
            )

        shutil.rmtree(OUTPUT)

    for split in SPLITS:
        for class_name in CLASSES.values():
            (OUTPUT / split / class_name).mkdir(
                parents=True,
                exist_ok=True,
            )

    counts = {
        split: Counter()
        for split in SPLITS
    }

    metadata = []
    crop_id = 1

    for split in SPLITS:

        image_dir = SOURCE / "images" / split
        label_dir = SOURCE / "labels" / split

        for image_path in sorted(image_dir.iterdir()):

            if (
                not image_path.is_file()
                or image_path.suffix.lower() not in IMAGE_EXTS
            ):
                continue

            label_path = (
                label_dir / f"{image_path.stem}.txt"
            )

            labels = read_labels(label_path)

            if not labels:
                continue

            with Image.open(image_path) as image:

                image = image.convert("RGB")
                image_w, image_h = image.size

                for object_index, label in enumerate(
                    labels,
                    start=1,
                ):

                    class_id, xc, yc, w, h = label
                    class_name = CLASSES[class_id]

                    x1, y1, x2, y2 = crop_coords(
                        xc,
                        yc,
                        w,
                        h,
                        image_w,
                        image_h,
                    )

                    crop = image.crop(
                        (
                            round(x1),
                            round(y1),
                            round(x2),
                            round(y2),
                        )
                    )

                    filename = (
                        f"{split}_"
                        f"{class_name}_"
                        f"{crop_id:05d}_"
                        f"{image_path.stem}_"
                        f"obj{object_index}.jpg"
                    )

                    output_path = (
                        OUTPUT
                        / split
                        / class_name
                        / filename
                    )

                    crop.save(
                        output_path,
                        format="JPEG",
                        quality=97,
                        subsampling=0,
                    )

                    counts[split][class_name] += 1

                    metadata.append({
                        "crop_id": crop_id,
                        "split": split,
                        "class_id": class_id,
                        "class_name": class_name,
                        "source_image": image_path.name,
                        "object_index": object_index,
                        "bbox_area_ratio": w * h,
                        "crop_width": crop.width,
                        "crop_height": crop.height,
                        "crop_path": str(
                            output_path.relative_to(ROOT)
                        ),
                    })

                    crop_id += 1

    metadata_csv = OUTPUT / "metadata.csv"

    with metadata_csv.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(metadata[0].keys()),
        )

        writer.writeheader()
        writer.writerows(metadata)

    summary = {
        "known_classes": [
            "haccp",
            "fda",
            "gmp",
            "iso_22000",
            "ocop",
        ],
        "unknown_class": "khac",
        "splits": {},
        "total_crops": 0,
    }

    for split in SPLITS:

        class_counts = {
            name: counts[split][name]
            for name in CLASSES.values()
        }

        total = sum(class_counts.values())

        summary["splits"][split] = {
            "total_crops": total,
            "class_counts": class_counts,
        }

        summary["total_crops"] += total

    (OUTPUT / "dataset_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ZIP bằng Python để dùng dấu "/" chuẩn,
    # tránh lỗi Windows ZIP ở Run 4.
    if ZIP_OUT.exists():
        ZIP_OUT.unlink()

    with zipfile.ZipFile(
        ZIP_OUT,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zf:

        for path in OUTPUT.rglob("*"):

            if not path.is_file():
                continue

            archive_path = (
                Path(OUTPUT.name)
                / path.relative_to(OUTPUT)
            ).as_posix()

            zf.write(
                path,
                arcname=archive_path,
            )

    print("=" * 70)
    print("DATASET LOGO CLASSIFIER")
    print("=" * 70)

    for split in SPLITS:
        print(
            f"{split:5s}: "
            f"{summary['splits'][split]['total_crops']} crop"
        )

        print(
            "      ",
            summary["splits"][split]["class_counts"],
        )

    print()
    print("Tổng crop:", summary["total_crops"])
    print("Dataset :", OUTPUT)
    print("ZIP     :", ZIP_OUT)

    print()
    print(
        "Lưu ý: 'khac' sẽ dùng như UNKNOWN, "
        "không coi là một loại logo thống nhất."
    )


if __name__ == "__main__":
    main()
