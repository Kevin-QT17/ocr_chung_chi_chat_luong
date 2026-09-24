import cv2
import numpy as np

from app.services.image_utils import decode_image


def test_decode_image_returns_rgb_array():
    bgr = np.zeros((12, 16, 3), dtype=np.uint8)
    bgr[:, :, 2] = 255  # red in BGR encoding
    ok, encoded = cv2.imencode('.jpg', bgr)
    assert ok

    rgb = decode_image(encoded.tobytes())
    assert rgb.shape == (12, 16, 3)
    assert rgb.dtype == np.uint8
    # JPEG is lossy, so just verify red channel dominates blue.
    assert float(rgb[:, :, 0].mean()) > float(rgb[:, :, 2].mean())


def test_decode_image_rejects_invalid_bytes():
    try:
        decode_image(b'not-an-image')
    except ValueError as exc:
        assert 'Không đọc được ảnh' in str(exc)
    else:
        raise AssertionError('Expected ValueError')
