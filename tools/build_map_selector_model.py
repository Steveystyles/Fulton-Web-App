from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools import map_selector_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the local map place selector model from review feedback.")
    parser.add_argument("--training-dir", type=Path, default=map_selector_model.DEFAULT_TRAINING_DIR)
    parser.add_argument("--out", type=Path, default=map_selector_model.DEFAULT_MODEL_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = map_selector_model.build_model_from_training_dir(args.training_dir)
    map_selector_model.save_model(model, args.out)
    print(
        json.dumps(
            {
                "model_path": str(args.out),
                "row_count": model.get("row_count", 0),
                "feature_count": model.get("feature_count", 0),
                "training_mae": model.get("training_mae"),
                "baseline_mae": model.get("baseline_mae"),
                "top_positive_features": model.get("top_positive_features", [])[:6],
                "top_negative_features": model.get("top_negative_features", [])[:6],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
