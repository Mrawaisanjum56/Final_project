

import logging
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from django.conf import settings

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_LOAD_FAILED = False

# Model output index -> grade mapping.
# Trained class order: ["good", "average", "bad"]
# Display as:         ["A",    "B",       "C"]
DISPLAY_CLASS_ORDER = ("A", "B", "C")


def _load_model():
    """
    Lazy-load and cache the trained Keras model from settings.WHEAT_QUALITY_MODEL_PATH.

    Returns:
        model or None (if unavailable)
    """
    global _MODEL, _MODEL_LOAD_FAILED
    if _MODEL is not None or _MODEL_LOAD_FAILED:
        return _MODEL

    try:
        from tensorflow import keras
    except (ImportError, OSError) as exc:
        _MODEL_LOAD_FAILED = True
        logger.warning("TensorFlow unavailable; cannot load wheat model: %s", exc)
        return None

    model_path = getattr(settings, "WHEAT_QUALITY_MODEL_PATH", None)
    if not model_path:
        _MODEL_LOAD_FAILED = True
        logger.error("WHEAT_QUALITY_MODEL_PATH is not set in ecommers/settings.py")
        return None

    model_path = Path(model_path)
    if not model_path.exists():
        _MODEL_LOAD_FAILED = True
        logger.error("Wheat model file not found: %s", model_path)
        return None

    try:
        _MODEL = keras.models.load_model(model_path)
    except Exception as exc:
        _MODEL_LOAD_FAILED = True
        logger.exception("Failed to load wheat model from %s: %s", model_path, exc)
        return None

    logger.info("Wheat quality model loaded: %s", model_path)
    return _MODEL


def _preprocess_224_rgb(image_input):
    """
    Convert any incoming image (Django ImageFieldFile or file path) into a model-ready
    batch tensor shaped (1, 224, 224, 3), using MobileNetV2 preprocess_input
    (matches your training pipeline).

    Raises:
        ValueError if image cannot be read/decoded.
    """
    try:
        # If it's a Django ImageFieldFile, ensure file is opened
        if hasattr(image_input, "open"):
            image_input.open()

        img = Image.open(image_input).convert("RGB").resize((224, 224))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Invalid image file. Please upload a valid image.") from exc

    arr = np.asarray(img, dtype=np.float32)          # shape (224,224,3) in 0..255 float
    arr = np.expand_dims(arr, axis=0)                # shape (1,224,224,3)

    try:
        from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
    except (ImportError, OSError) as exc:
        raise ValueError("TensorFlow MobileNetV2 preprocess_input is unavailable.") from exc

    arr = preprocess_input(arr)
    return arr


def assess_wheat_quality(image_input):
    """
    Run inference and return:
        (grade, confidence_pct)

    grade:
        "A" | "B" | "C" | None
    confidence_pct:
        float (0..100) | None

    Notes:
    - If model isn't available, returns (None, None) so your listing flow doesn't crash.
    - If image is invalid, raises ValueError (caller can catch and show message).
    """
    if image_input is None:
        return None, None

    model = _load_model()
    if model is None:
        return None, None

    x = _preprocess_224_rgb(image_input)

    probs = model.predict(x, verbose=0)
    probs = np.asarray(probs).reshape(-1)

    if probs.shape[0] != 3:
        raise ValueError(f"Expected 3-class output (good/average/bad). Got shape={probs.shape}.")

    idx = int(np.argmax(probs))
    grade = DISPLAY_CLASS_ORDER[idx]
    confidence_pct = float(probs[idx]) * 100.0

    # clamp just in case of numeric weirdness
    confidence_pct = max(0.0, min(100.0, confidence_pct))

    return grade, round(confidence_pct, 2)