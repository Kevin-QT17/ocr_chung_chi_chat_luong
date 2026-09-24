from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

UNKNOWN = "khac"
KNOWN_CLASSES = {"haccp", "fda", "gmp", "iso_22000", "ocop"}
REFERENCE_DIR = Path(__file__).resolve().parents[2] / "reference_logos"

# Conservative visual fallback. We prefer missing a difficult logo over
# classifying a random product image as a certificate.
MIN_INLIERS = 6
MIN_APPEARANCE_CORRELATION = 0.30
MIN_VALID_COVERAGE = 0.75
RATIO_TEST = 0.68
RANSAC_REPROJECTION = 4.0
QUERY_MAX_SIDE = 1600
REFERENCE_TARGET_SIDE = 500


def _class_from_name(name: str) -> str:
    if name.startswith("iso_22000"):
        return "iso_22000"
    return name.split("_", 1)[0]


def _orb():
    return cv2.ORB_create(
        nfeatures=2200,
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=15,
        fastThreshold=7,
    )


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _resize_max(gray: np.ndarray, max_side: int) -> np.ndarray:
    h, w = gray.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return gray
    scale = max_side / float(long_side)
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _resize_reference(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape[:2]
    long_side = max(h, w)
    if long_side >= REFERENCE_TARGET_SIDE:
        return gray
    scale = REFERENCE_TARGET_SIDE / float(max(long_side, 1))
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _masked_correlation(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    x = a[mask].astype(np.float32)
    y = b[mask].astype(np.float32)
    if x.size < 200:
        return -1.0
    x_std = float(x.std())
    y_std = float(y.std())
    if x_std < 1e-6 or y_std < 1e-6:
        return -1.0
    x = (x - float(x.mean())) / x_std
    y = (y - float(y.mean())) / y_std
    return float((x * y).mean())


@lru_cache(maxsize=1)
def _reference_features():
    if not REFERENCE_DIR.exists():
        return []

    orb = _orb()
    features = []
    for path in sorted(REFERENCE_DIR.glob("*.jpg")):
        class_name = _class_from_name(path.name)
        if class_name not in KNOWN_CLASSES:
            continue
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None or gray.size == 0:
            continue
        gray = _resize_reference(gray)
        keypoints, descriptors = orb.detectAndCompute(gray, None)
        if descriptors is None or not keypoints or len(keypoints) < 4:
            continue
        features.append({
            "class_name": class_name,
            "reference": path.name,
            "gray": gray,
            "keypoints": keypoints,
            "descriptors": descriptors,
        })
    return features


def _match_reference(query_gray, query_kp, query_desc, ref: dict) -> dict:
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(ref["descriptors"], query_desc, k=2)
    good = [m for m, n in pairs if m.distance < RATIO_TEST * n.distance]

    inliers = 0
    correlation = -1.0
    valid_coverage = 0.0

    if len(good) >= 5:
        src = np.float32([
            ref["keypoints"][m.queryIdx].pt for m in good
        ]).reshape(-1, 1, 2)
        dst = np.float32([
            query_kp[m.trainIdx].pt for m in good
        ]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            src,
            dst,
            cv2.RANSAC,
            RANSAC_REPROJECTION,
        )
        if mask is not None:
            inliers = int(mask.sum())

        if homography is not None and inliers >= 4:
            try:
                inverse = np.linalg.inv(homography)
                ref_gray = ref["gray"]
                size = (ref_gray.shape[1], ref_gray.shape[0])
                warped = cv2.warpPerspective(query_gray, inverse, size)
                valid_source = np.full(query_gray.shape, 255, dtype=np.uint8)
                valid = cv2.warpPerspective(valid_source, inverse, size) > 0
                valid_coverage = float(valid.mean())
                if valid_coverage >= MIN_VALID_COVERAGE:
                    correlation = _masked_correlation(ref_gray, warped, valid)
            except (cv2.error, np.linalg.LinAlgError):
                pass

    return {
        "class_name": ref["class_name"],
        "reference": ref["reference"],
        "good_matches": len(good),
        "inliers": inliers,
        "appearance_correlation": correlation,
        "valid_coverage": valid_coverage,
    }


def match_visual_logo(rgb: np.ndarray) -> dict:
    """Conservative local visual similarity fallback.

    Each known logo crop is matched against the full image using ORB features,
    Lowe's ratio test and RANSAC homography. A candidate is accepted only when
    the homography has enough inliers *and* the perspective-normalized patch is
    visually correlated with the reference. The correlation check is important
    for rejecting accidental ORB matches on textured product photography.
    """
    refs = _reference_features()
    if not refs:
        return {
            "class_name": UNKNOWN,
            "score": 0.0,
            "reason": "reference_bank_missing",
            "reference": None,
            "inliers": 0,
            "good_matches": 0,
            "appearance_correlation": -1.0,
        }

    query_gray = _resize_max(_to_gray(rgb), QUERY_MAX_SIDE)
    orb = _orb()
    query_kp, query_desc = orb.detectAndCompute(query_gray, None)
    if query_desc is None or not query_kp:
        return {
            "class_name": UNKNOWN,
            "score": 0.0,
            "reason": "no_query_features",
            "reference": None,
            "inliers": 0,
            "good_matches": 0,
            "appearance_correlation": -1.0,
        }

    matches = [
        _match_reference(query_gray, query_kp, query_desc, ref)
        for ref in refs
    ]

    eligible = [
        row for row in matches
        if row["inliers"] >= MIN_INLIERS
        and row["valid_coverage"] >= MIN_VALID_COVERAGE
        and row["appearance_correlation"] >= MIN_APPEARANCE_CORRELATION
    ]

    if not eligible:
        raw_best = max(
            matches,
            key=lambda x: (
                x["inliers"],
                x["appearance_correlation"],
                x["good_matches"],
            ),
        )
        return {
            "class_name": UNKNOWN,
            "score": 0.0,
            "reason": (
                "visual_below_threshold:"
                f"inliers={raw_best['inliers']};"
                f"corr={raw_best['appearance_correlation']:.3f}"
            ),
            "reference": raw_best["reference"],
            "inliers": raw_best["inliers"],
            "good_matches": raw_best["good_matches"],
            "appearance_correlation": raw_best["appearance_correlation"],
            "valid_coverage": raw_best["valid_coverage"],
        }

    best = max(
        eligible,
        key=lambda x: (
            x["appearance_correlation"],
            x["inliers"],
            x["good_matches"],
        ),
    )

    # Operational score, not a calibrated probability. Correlation dominates,
    # while additional geometric inliers add a small bonus.
    score = min(
        100.0,
        65.0 + 30.0 * best["appearance_correlation"] + 1.5 * best["inliers"],
    )

    return {
        "class_name": best["class_name"],
        "score": float(score),
        "reason": (
            f"ORB_RANSAC:inliers={best['inliers']};"
            f"good={best['good_matches']};"
            f"corr={best['appearance_correlation']:.3f}"
        ),
        "reference": best["reference"],
        "inliers": best["inliers"],
        "good_matches": best["good_matches"],
        "appearance_correlation": best["appearance_correlation"],
        "valid_coverage": best["valid_coverage"],
    }
