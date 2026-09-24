import re
from rapidfuzz.fuzz import ratio
from unidecode import unidecode

UNKNOWN = "khac"


def normalize_text(text: str) -> str:
    text = unidecode(str(text or "")).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str):
    return [x for x in normalize_text(text).split() if len(x) >= 2]


def _token_similarity(text: str, target: str, min_length: int) -> float:
    best = 0.0
    for token in _tokens(text):
        if len(token) < min_length:
            continue
        best = max(best, float(ratio(token, target)))
    return best


def _detect_iso_22000(text: str):
    iso_score = 0.0
    number_score = 0.0
    for token in _tokens(text):
        if len(token) >= 3:
            alpha = token.replace("0", "O").replace("1", "I")
            iso_score = max(iso_score, float(ratio(alpha, "ISO")))
        if len(token) >= 4:
            numeric = token.replace("O", "0")
            number_score = max(number_score, float(ratio(numeric, "22000")))
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if len(compact) >= 7:
            prefix = compact[:3].replace("0", "O").replace("1", "I")
            suffix = compact[3:8].replace("O", "0")
            iso_score = max(iso_score, float(ratio(prefix, "ISO")))
            number_score = max(number_score, float(ratio(suffix, "22000")))
    if iso_score >= 70 and number_score >= 70:
        return True, min(iso_score, number_score)
    return False, 0.0


def classify_logo_text(text: str) -> dict:
    norm = normalize_text(text)
    compact = re.sub(r"[^A-Z0-9]", "", norm)
    if len(compact) < 3:
        return {"class_name": UNKNOWN, "score": 0.0, "reason": "text_too_short"}

    candidates = []
    iso_ok, iso_score = _detect_iso_22000(norm)
    if iso_ok:
        candidates.append(("iso_22000", iso_score, "ISO_like+22000_like"))

    for cls, target, threshold, min_len in [
        ("ocop", "OCOP", 75, 3),
        ("haccp", "HACCP", 75, 3),
        ("gmp", "GMP", 80, 3),
        ("fda", "FDA", 80, 3),
    ]:
        score = _token_similarity(norm, target, min_len)
        if score >= threshold:
            candidates.append((cls, score, f"{target}:{score:.1f}"))

    if not candidates:
        return {"class_name": UNKNOWN, "score": 0.0, "reason": "no_strict_evidence"}
    candidates.sort(key=lambda x: x[1], reverse=True)
    cls, score, reason = candidates[0]
    return {"class_name": cls, "score": float(score), "reason": reason}
