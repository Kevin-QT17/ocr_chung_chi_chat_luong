from __future__ import annotations

UNKNOWN = "khac"
KNOWN_CLASSES = {"haccp", "fda", "gmp", "iso_22000", "ocop"}


def _pick_best_known_detection(detections: list[dict]) -> dict | None:
    known = [d for d in detections if d.get("certificate_type") in KNOWN_CLASSES]
    if not known:
        return None
    return max(
        known,
        key=lambda d: (
            float(d.get("classification_score") or 0.0),
            float(d.get("detector_confidence") or 0.0),
        ),
    )


def resolve_certificate(
    enriched: list[dict],
    document_classification: dict,
    visual_classification: dict | None = None,
) -> dict:
    # 1) Strongest evidence: YOLO localized a region and OCR classified it.
    best = _pick_best_known_detection(enriched)
    if best is not None:
        return {
            "certificate_type": best["certificate_type"],
            "classification_source": "detector_crop_ocr",
            "classification_score": float(best.get("classification_score") or 0.0),
            "classification_reason": best.get("classification_reason") or "",
            "detector_status": "hit_known",
        }

    # 2) Full-page OCR can rescue a missed / wrong YOLO box when the textual
    # certificate name itself is readable.
    doc_cls = document_classification.get("class_name", UNKNOWN)
    if doc_cls in KNOWN_CLASSES:
        return {
            "certificate_type": doc_cls,
            "classification_source": "full_page_ocr_fallback",
            "classification_score": float(document_classification.get("score") or 0.0),
            "classification_reason": document_classification.get("reason") or "",
            "detector_status": "hit_unclassified" if enriched else "no_detection",
        }

    # 3) Conservative local-feature visual matcher. It is useful when the logo
    # is stylized (e.g. FDA REGISTERED) and EasyOCR cannot read the letters.
    visual_classification = visual_classification or {}
    visual_cls = visual_classification.get("class_name", UNKNOWN)
    if visual_cls in KNOWN_CLASSES:
        return {
            "certificate_type": visual_cls,
            "classification_source": "visual_orb_fallback",
            "classification_score": float(visual_classification.get("score") or 0.0),
            "classification_reason": visual_classification.get("reason") or "",
            "detector_status": "hit_unclassified" if enriched else "no_detection",
        }

    return {
        "certificate_type": UNKNOWN,
        "classification_source": "unknown",
        "classification_score": 0.0,
        "classification_reason": "no_supported_certificate_evidence",
        "detector_status": "hit_unclassified" if enriched else "no_detection",
    }
