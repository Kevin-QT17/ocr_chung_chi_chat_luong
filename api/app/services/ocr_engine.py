from __future__ import annotations

from functools import lru_cache
import cv2
import numpy as np
import torch
import easyocr


@lru_cache(maxsize=1)
def get_reader():
    return easyocr.Reader(["vi", "en"], gpu=bool(torch.cuda.is_available()))


def _resize_for_document(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    long_side = max(h, w)
    if long_side > 1900:
        s = 1900.0 / long_side
        rgb = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    elif long_side < 1100:
        s = 1100.0 / max(long_side, 1)
        rgb = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return rgb


def read_document(rgb: np.ndarray) -> dict:
    rgb = _resize_for_document(rgb)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    out = get_reader().readtext(
        clahe,
        detail=1,
        paragraph=False,
        decoder="greedy",
        batch_size=16,
        workers=0,
        canvas_size=1920,
        mag_ratio=1.0,
    )
    items = []
    for bbox, text, conf in out:
        text = str(text).strip()
        if not text:
            continue
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        items.append({
            "text": text,
            "ocr_confidence": float(conf),
            "x": sum(xs) / len(xs),
            "y": sum(ys) / len(ys),
        })
    items.sort(key=lambda r: (round(r["y"] / 20.0), r["x"]))
    return {"text": " | ".join(x["text"] for x in items), "items": items}


def _context_crop(rgb: np.ndarray, box, padding: float) -> np.ndarray:
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = map(float, box)
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    x1 = max(0, int(round(x1 - bw * padding)))
    y1 = max(0, int(round(y1 - bh * padding)))
    x2 = min(w, int(round(x2 + bw * padding)))
    y2 = min(h, int(round(y2 + bh * padding)))
    return rgb[y1:y2, x1:x2]


def _read_crop_once(rgb: np.ndarray) -> list[str]:
    if rgb.size == 0:
        return []
    h, w = rgb.shape[:2]
    if max(h, w) < 900:
        s = 900.0 / max(h, w, 1)
        rgb = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    texts = get_reader().readtext(
        clahe,
        detail=0,
        paragraph=False,
        decoder="greedy",
        batch_size=16,
        workers=0,
        canvas_size=1280,
        mag_ratio=1.0,
    )
    seen, clean = set(), []
    for value in texts:
        value = str(value).strip()
        key = value.upper()
        if value and key not in seen:
            seen.add(key)
            clean.append(value)
    return clean


def read_logo_contexts(rgb: np.ndarray, box) -> dict:
    result = {}
    merged = []
    for name, padding in (("medium", 0.50), ("wide", 1.00)):
        texts = _read_crop_once(_context_crop(rgb, box, padding))
        result[name] = " | ".join(texts)
        merged.extend(texts)
    result["merged"] = " | ".join(merged)
    return result
