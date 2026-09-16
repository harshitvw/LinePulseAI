"""Shared, cached fixtures for the LinePulse AI verification suite."""

from __future__ import annotations

import copy
import sys
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
WORKBOOK = PROJECT_ROOT / "data" / "source" / "Synthetic_Dataset.xlsx"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from linepulse.analytics import DEFAULT_ARTIFACT_PATH  # noqa: E402

MODEL_ARTIFACT = Path(DEFAULT_ARTIFACT_PATH)


@lru_cache(maxsize=1)
def official_bundle():
    from linepulse.data import load_official_data

    return load_official_data(WORKBOOK)


@lru_cache(maxsize=1)
def trained_model():
    from linepulse.analytics import load_or_train_model

    return load_or_train_model(official_bundle(), MODEL_ARTIFACT)


@lru_cache(maxsize=1)
def official_assessments():
    from linepulse.risk import build_asset_assessments

    return tuple(build_asset_assessments(official_bundle(), trained_model()))


@lru_cache(maxsize=1)
def label_free_model():
    """Train the declared analytical fallback after removing all hint labels."""

    from linepulse.analytics import train_degradation_model

    bundle = cloned_bundle()
    bundle.weekly["DegradationTarget"] = 0
    return train_degradation_model(bundle)


def cloned_bundle():
    """Return a fully independent copy so mutation tests cannot pollute fixtures."""

    return copy.deepcopy(official_bundle())


def metadata_dict(model=None) -> dict:
    model = model or trained_model()
    metadata = getattr(model, "metadata", {})
    return dict(metadata)
