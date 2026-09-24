from __future__ import annotations

import cv2
import numpy as np


def decode_image(content: bytes) -> np.ndarray:
    """Decode uploaded image bytes to an RGB NumPy array."""
    if not content:
        raise ValueError("File ảnh rỗng.")

    data = np.frombuffer(content, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Không đọc được ảnh đầu vào.")

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
