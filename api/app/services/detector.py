from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from ultralytics import YOLO

MODEL_PATH = Path(__file__).resolve().parents[2] / "weights" / "best.pt"


@lru_cache(maxsize=1)
def get_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Không tìm thấy YOLO checkpoint: {MODEL_PATH}")
    return YOLO(str(MODEL_PATH))


def detect(rgb, confidence: float = 0.40, imgsz: int = 960) -> list[dict]:
    results = get_model().predict(
        source=rgb,
        conf=float(confidence),
        imgsz=int(imgsz),
        verbose=False,
    )
    detections = []
    if not results:
        return detections
    boxes = results[0].boxes
    if boxes is None:
        return detections
    for box in boxes:
        xyxy = box.xyxy[0].detach().cpu().tolist()
        conf = float(box.conf[0].detach().cpu())
        detections.append({
            "bbox": [round(float(x), 2) for x in xyxy],
            "detector_confidence": conf,
        })
    detections.sort(key=lambda x: x["detector_confidence"], reverse=True)
    return detections
