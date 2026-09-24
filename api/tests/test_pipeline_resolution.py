from app.services.resolver import resolve_certificate


def _visual_unknown():
    return {"class_name": "khac", "score": 0.0, "reason": "below"}


def test_prefers_known_detector_crop():
    dets = [{
        "certificate_type": "ocop",
        "classification_score": 85.7,
        "classification_reason": "OCOP:85.7",
        "detector_confidence": 0.44,
    }]
    doc = {"class_name": "haccp", "score": 100.0, "reason": "HACCP:100.0"}
    vis = {"class_name": "fda", "score": 100.0, "reason": "visual"}
    out = resolve_certificate(dets, doc, vis)
    assert out["certificate_type"] == "ocop"
    assert out["classification_source"] == "detector_crop_ocr"
    assert out["detector_status"] == "hit_known"


def test_full_page_ocr_fallback_before_visual():
    doc = {"class_name": "iso_22000", "score": 100.0, "reason": "ISO_like+22000_like"}
    vis = {"class_name": "fda", "score": 100.0, "reason": "visual"}
    out = resolve_certificate([], doc, vis)
    assert out["certificate_type"] == "iso_22000"
    assert out["classification_source"] == "full_page_ocr_fallback"
    assert out["detector_status"] == "no_detection"


def test_visual_fallback_when_text_and_detector_fail():
    doc = {"class_name": "khac", "score": 0.0, "reason": "no_strict_evidence"}
    vis = {"class_name": "fda", "score": 100.0, "reason": "ORB_RANSAC:inliers=12"}
    out = resolve_certificate([], doc, vis)
    assert out["certificate_type"] == "fda"
    assert out["classification_source"] == "visual_orb_fallback"
    assert out["detector_status"] == "no_detection"


def test_visual_fallback_after_unclassified_detector():
    dets = [{
        "certificate_type": "khac",
        "classification_score": 0.0,
        "classification_reason": "no_strict_evidence",
        "detector_confidence": 0.42,
    }]
    doc = {"class_name": "khac", "score": 0.0, "reason": "no_strict_evidence"}
    vis = {"class_name": "gmp", "score": 90.0, "reason": "ORB_RANSAC:inliers=10"}
    out = resolve_certificate(dets, doc, vis)
    assert out["certificate_type"] == "gmp"
    assert out["classification_source"] == "visual_orb_fallback"
    assert out["detector_status"] == "hit_unclassified"


def test_unknown_when_no_supported_evidence():
    out = resolve_certificate(
        [],
        {"class_name": "khac", "score": 0.0, "reason": "no_strict_evidence"},
        _visual_unknown(),
    )
    assert out["certificate_type"] == "khac"
    assert out["classification_source"] == "unknown"
    assert out["detector_status"] == "no_detection"
