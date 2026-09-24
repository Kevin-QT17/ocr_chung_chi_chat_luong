from pathlib import Path
import cv2
import numpy as np

from app.services.visual_matcher import match_visual_logo


def test_reference_bank_exists():
    root = Path(__file__).resolve().parents[1] / "reference_logos"
    refs = list(root.glob("*.jpg"))
    assert len(refs) >= 31


def test_fda_reference_can_be_found_inside_larger_canvas():
    root = Path(__file__).resolve().parents[1] / "reference_logos"
    ref = cv2.imread(str(root / "fda_001_anh_000048.jpg"))
    assert ref is not None
    h, w = ref.shape[:2]
    canvas = np.full((max(800, h + 300), max(1100, w + 500), 3), 245, dtype=np.uint8)
    y, x = 140, 260
    canvas[y:y+h, x:x+w] = ref
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    result = match_visual_logo(rgb)
    assert result["class_name"] == "fda"
    assert result["inliers"] >= 6
    assert result["appearance_correlation"] >= 0.30
