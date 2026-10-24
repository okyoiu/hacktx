"""InsightFace face prints, shared by live capture and enrollment selfies so both use the same model."""
from functools import lru_cache

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _model():
    from insightface.app import FaceAnalysis

    # buffalo_l weights are for non-commercial research use: fine for the hackathon, swap before selling.
    model = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    model.prepare(ctx_id=0)
    return model


def embed(bgr: np.ndarray) -> np.ndarray | None:
    """512-number unit-length print of the largest face in a BGR image, or None if there is no face."""
    if bgr.size == 0:
        return None
    faces = _model().get(bgr)
    if not faces:
        return None
    biggest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return biggest.normed_embedding.astype(np.float32)


def embed_image(data: bytes) -> np.ndarray | None:
    """Same as embed(), for an uploaded JPEG/PNG."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return None if img is None else embed(img)
