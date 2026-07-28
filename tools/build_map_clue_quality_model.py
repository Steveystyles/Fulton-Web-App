from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools import map_clue_quality_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the local Hard, Medium, and Easy clue-quality models.",
    )
    parser.add_argument(
        "--training-dir",
        type=Path,
        default=map_clue_quality_model.DEFAULT_TRAINING_DIR,
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=map_clue_quality_model.DEFAULT_MODEL_PATH,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = map_clue_quality_model.build_model_from_training_dir(args.training_dir)
    map_clue_quality_model.save_model(model, args.out)
    print(
        json.dumps(
            {
                "model_path": str(args.out),
                "row_count": model.get("row_count", 0),
                "source_counts": model.get("source_counts", {}),
                "level_counts": model.get("level_counts", {}),
                "validation": model.get("validation", {}),
                "validation_by_level": model.get("validation_by_level", {}),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
