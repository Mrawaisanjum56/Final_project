import logging

import numpy as np
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

_MOBILENET_MODEL = None
_MOBILENET_PREPROCESS = None
_MOBILENET_IMPORT_FAILED = False


def _load_mobilenet():
    global _MOBILENET_MODEL, _MOBILENET_PREPROCESS, _MOBILENET_IMPORT_FAILED
    if _MOBILENET_MODEL is not None or _MOBILENET_IMPORT_FAILED:
        return _MOBILENET_MODEL, _MOBILENET_PREPROCESS

    try:
        from tensorflow.keras.applications import MobileNetV2
        from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
    except (ImportError, OSError) as exc:
        _MOBILENET_IMPORT_FAILED = True
        logger.warning("MobileNetV2 unavailable, using fallback heuristic: %s", exc)
        return None, None

    _MOBILENET_MODEL = MobileNetV2(weights='imagenet')
    _MOBILENET_PREPROCESS = preprocess_input
    return _MOBILENET_MODEL, _MOBILENET_PREPROCESS


def _image_to_array(image_input):
    try:
        if hasattr(image_input, 'open'):
            image_input.open()
        image = Image.open(image_input).convert('RGB').resize((224, 224))
        return np.array(image, dtype=np.float32)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError('Unable to process image. Please upload a valid image file.') from exc


def _grade_from_confidence(confidence_pct):
    if confidence_pct >= 80:
        return 'A'
    if confidence_pct >= 60:
        return 'B'
    return 'C'


def assess_wheat_quality(image_input):
    if image_input is None:
        return None, None

    image_array = _image_to_array(image_input)
    model, preprocess = _load_mobilenet()

    if model is not None and preprocess is not None:
        batch = np.expand_dims(preprocess(image_array.copy()), axis=0)
        probs = model.predict(batch, verbose=0)[0]
        confidence_pct = float(np.max(probs) * 100)
        grade = _grade_from_confidence(confidence_pct)
        return grade, round(confidence_pct, 2)

    grayscale = np.mean(image_array, axis=2)
    brightness = float(np.mean(grayscale) / 255.0)
    texture = float(np.std(grayscale) / 128.0)
    heuristic_confidence = max(0.0, min(100.0, (0.6 * brightness + 0.4 * texture) * 100.0))
    grade = _grade_from_confidence(heuristic_confidence)
    return grade, round(heuristic_confidence, 2)
