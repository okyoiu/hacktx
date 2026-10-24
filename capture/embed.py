"""InsightFace face prints, shared by live capture and enrollment selfies so both use the same model."""
from functools import lru_cache

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _model():
    from insightface.app import FaceAnalysis

    # buffalo_l weights are for non-commercial research use: fine for the hackathon, swap before selling.
    model = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    # 1280 on top of the default sizes: a whole Retina frame shrinks ~3x at 640 and 24px faces vanish; costs ~0.13 s more per pass
    model.prepare(ctx_id=0, det_size=[(128, 128), (640, 640), (1280, 1280)])
    return model


def faces_in(bgr: np.ndarray) -> list:
    """Every face in a BGR image; each has .bbox (x1, y1, x2, y2 in pixels) and a unit-length .normed_embedding."""
    return _model().get(bgr) if bgr.size else []


def embed(bgr: np.ndarray) -> np.ndarray | None:
    """512-number unit-length print of the largest face in a BGR image, or None if there is no face."""
    faces = faces_in(bgr)
    if not faces:
        return None
    biggest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return biggest.normed_embedding.astype(np.float32)


def embed_image(data: bytes) -> np.ndarray | None:
    """Same as embed(), for an uploaded JPEG/PNG."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return None if img is None else embed(img)
