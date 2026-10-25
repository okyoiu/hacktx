"""InsightFace face prints, shared by live capture and enrollment selfies so both use the same model."""
import os
from functools import lru_cache

# OpenCV reads this when it loads: without it a small, highly compressible upload can decode to gigabytes
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))  # 40 MP: bigger than any phone selfie

import numpy as np


@lru_cache(maxsize=1)
def _model():
    from insightface.app import FaceAnalysis

    # buffalo_l weights are for non-commercial research use: fine for the hackathon, swap before selling.
    model = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    # 1280 on top of the default sizes: a whole Retina frame shrinks ~3x at 640 and 24px faces vanish; costs ~0.13 s more per pass
    model.prepare(ctx_id=0, det_size=[(128, 128), (640, 640), (1280, 1280)])
    return model


def find_faces(bgr: np.ndarray) -> list:
    """Every face in a BGR image with .bbox (x1, y1, x2, y2 in pixels) and lip landmarks, but no print yet: a print costs
    about 0.18 s per face, so add_print only the ones that need it."""
    from insightface.app.common import Face

    model = _model()
    if not bgr.size:
        return []
    boxes, kpss = model.det_model.detect(bgr, max_num=0, metric="default")
    faces = [Face(bbox=b[:4], kps=None if kpss is None else kpss[i], det_score=b[4]) for i, b in enumerate(boxes)]
    for face in faces:
        model.models["landmark_3d_68"].get(bgr, face)
    return faces


def add_print(bgr: np.ndarray, face) -> None:
    """Give a face from find_faces its unit-length .normed_embedding."""
    _model().models["recognition"].get(bgr, face)


def faces_in(bgr: np.ndarray) -> list:
    """find_faces with every print added."""
    faces = find_faces(bgr)
    for face in faces:
        add_print(bgr, face)
    return faces


def warm_up() -> None:
    """The first pass through each model takes ~3 s; do it before the call so the first name card isn't late."""
    from insightface.data import get_image

    faces_in(get_image("t1"))  # InsightFace's bundled sample photo


def mouths_in(bgr: np.ndarray) -> list:
    """Faces with lip landmarks (.bbox, .landmark_3d_68) but no prints: quick enough to run on every frame."""
    from insightface.app.common import Face

    model = _model()
    # InsightFace's default sizes: 128 finds faces that fill the frame; faces that need 1280 are too small to read lips
    boxes, kpss = model.det_model.detect(bgr, input_size=[(128, 128), (640, 640)])
    faces = [Face(bbox=b[:4], kps=k, det_score=b[4]) for b, k in zip(boxes, kpss)]
    for face in faces:
        model.models["landmark_3d_68"].get(bgr, face)
    return faces


def embed(bgr: np.ndarray) -> np.ndarray | None:
    """512-number unit-length print of the largest face in a BGR image, or None if there is no face."""
    faces = faces_in(bgr)
    if not faces:
        return None
    biggest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return biggest.normed_embedding.astype(np.float32)


def embed_image(data: bytes) -> np.ndarray | None:
    """Same as embed(), for an uploaded JPEG/PNG."""
    import cv2

    try:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:  # over the pixel cap
        return None
    return None if img is None else embed(img)
