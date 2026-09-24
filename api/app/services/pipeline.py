from __future__ import annotations

from .detector import detect
from .image_utils import decode_image
from .ocr_engine import read_document, read_logo_contexts
from .logo_rules import classify_logo_text
from .resolver import resolve_certificate
from .visual_matcher import match_visual_logo
from .date_extractor import extract as extract_dates


def analyze_image(content: bytes, detector_confidence: float = 0.40, imgsz: int = 960) -> dict:
    rgb = decode_image(content)

    # OCR toàn trang chạy một lần và được tái sử dụng cho:
    # - Run 7D date extraction
    # - fallback phân loại khi YOLO bỏ sót hoặc crop không đọc được logo.
    document_ocr = read_document(rgb)
    document_classification = classify_logo_text(document_ocr["text"])
    dates = extract_dates(document_ocr["text"])

    detections = detect(rgb, confidence=detector_confidence, imgsz=imgsz)
    enriched = []
    for det in detections:
        contexts = read_logo_contexts(rgb, det["bbox"])
        logo = classify_logo_text(contexts["merged"])
        enriched.append({
            **det,
            "certificate_type": logo["class_name"],
            "classification_score": logo["score"],
            "classification_reason": logo["reason"],
            "logo_ocr": {
                "medium": contexts["medium"],
                "wide": contexts["wide"],
            },
        })

    # Run the visual fallback only if neither localized OCR nor full-page OCR
    # already identified a supported certificate. This avoids extra CPU cost in
    # the common successful path.
    has_known_crop = any(
        d.get("certificate_type") in {"haccp", "fda", "gmp", "iso_22000", "ocop"}
        for d in enriched
    )
    has_known_document = document_classification.get("class_name") in {
        "haccp", "fda", "gmp", "iso_22000", "ocop"
    }
    if has_known_crop or has_known_document:
        visual_classification = {
            "class_name": "khac",
            "score": 0.0,
            "reason": "not_needed",
            "reference": None,
            "inliers": 0,
            "good_matches": 0,
        }
    else:
        visual_classification = match_visual_logo(rgb)

    resolved = resolve_certificate(
        enriched,
        document_classification,
        visual_classification,
    )

    date_payload = {
        key: dates.get(key)
        for key in [
            "issue_date", "valid_from", "expiry_date", "decision_date",
            "issue_date_confidence", "valid_from_confidence",
            "expiry_date_confidence", "decision_date_confidence",
            "issue_date_evidence", "valid_from_evidence",
            "expiry_date_evidence", "decision_date_evidence",
        ]
    }

    return {
        "image": {"width": int(rgb.shape[1]), "height": int(rgb.shape[0])},
        "detector": {"confidence_threshold": detector_confidence, "imgsz": imgsz},
        "detector_status": resolved["detector_status"],
        "certificate_type": resolved["certificate_type"],
        "classification_source": resolved["classification_source"],
        "classification_score": resolved["classification_score"],
        "classification_reason": resolved["classification_reason"],
        "detections": enriched,
        "full_page_classification": {
            "certificate_type": document_classification["class_name"],
            "score": document_classification["score"],
            "reason": document_classification["reason"],
        },
        "visual_classification": visual_classification,
        "dates": date_payload,
        "document_ocr_text": document_ocr["text"],
    }
