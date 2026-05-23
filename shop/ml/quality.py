import logging
import numpy as np
from PIL import Image, UnidentifiedImageError

from django.conf import settings

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_LOAD_FAILED = False

# Must match your training label order:
# if your model was trained in different order, change this tuple accordingly.
CLASS_ORDER = ("A", "B", "C")


def _load_model():
    global _MODEL, _MODEL_LOAD_FAILED
    if _MODEL is not None or _MODEL_LOAD_FAILED:
        return _MODEL

    try:
        from tensorflow import keras
    except (ImportError, OSError) as exc:
        _MODEL_LOAD_FAILED = True
        logger.warning("TensorFlow unavailable; cannot load .keras model: %s", exc)
        return None

    model_path = getattr(settings, "WHEAT_QUALITY_MODEL_PATH", None)
    if not model_path:
        _MODEL_LOAD_FAILED = True
        logger.error("WHEAT_QUALITY_MODEL_PATH is not configured in settings.py")
        return None

    _MODEL = keras.models.load_model(model_path)
    return _MODEL


def _preprocess_224_rgb(image_input):
    """
    Returns float32 array shaped (1, 224, 224, 3)
    Normalization: 0..1 (common). If your training used another scheme
    (e.g. [-1,1] or ImageNet preprocess), tell me and I’ll adjust.
    """
    try:
        if hasattr(image_input, "open"):
            image_input.open()
        img = Image.open(image_input).convert("RGB").resize((224, 224))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Invalid image file. Please upload a valid image.") from exc

    arr = np.asarray(img, dtype=np.float32) / 255.0
    return np.expand_dims(arr, axis=0)


def assess_wheat_quality(image_input):
    """
    Returns: (grade: 'A'|'B'|'C'|None, confidence_pct: float|None)
    """
    if image_input is None:
        return None, None

    model = _load_model()
    if model is None:
        # If you want: raise error instead of returning None
        return None, None

    x = _preprocess_224_rgb(image_input)

    # Expecting shape (1, 3) probabilities for A/B/C
    probs = model.predict(x, verbose=0)
    probs = np.asarray(probs).reshape(-1)

    if probs.shape[0] != 3:
        raise ValueError(f"Expected 3-class output (A/B/C). Got shape={probs.shape}.")

    idx = int(np.argmax(probs))
    grade = CLASS_ORDER[idx]
    confidence_pct = float(probs[idx]) * 100.0
    return grade, round(confidence_pct, 2)