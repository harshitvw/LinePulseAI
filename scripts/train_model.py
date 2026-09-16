"""Train the official-data degradation detector and save its artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from linepulse.analytics import DEFAULT_ARTIFACT_PATH, train_degradation_model
from linepulse.data import load_official_data


def main() -> None:
    data = load_official_data()
    model = train_degradation_model(data, artifact_path=DEFAULT_ARTIFACT_PATH)
    summary = {
        "artifact": str(DEFAULT_ARTIFACT_PATH.relative_to(PROJECT_ROOT)),
        "model_family": model.metadata["model_family"],
        "semantic_label": model.metadata["semantic_label"],
        "training_rows": model.metadata["training_rows"],
        "asset_groups": model.metadata["asset_groups"],
        "validation_strategy": model.metadata["validation_strategy"],
        "group_leakage_detected": model.metadata["group_leakage_detected"],
        "cross_validation": model.metadata["cross_validation"],
        "production_validated": model.metadata["production_validated"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

