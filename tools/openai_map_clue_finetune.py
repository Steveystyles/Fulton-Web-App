from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import openai_quiz_finetune

DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_REGISTRY_PATH = DEFAULT_TRAINING_DIR / "map_model_registry.json"
DEFAULT_ENV_FILE = PROJECT_DIR / ".env.local"
DEFAULT_TRAIN_PATTERNS = ("map_clue_sft_train_*.jsonl",)
DEFAULT_EVAL_PATTERNS = ("map_clue_eval_*.jsonl",)
DEFAULT_NEGATIVE_PATTERNS = ("map_clue_negative_*.jsonl",)
SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."


@dataclass(frozen=True)
class PreparedMapArtifacts:
    train_path: Path
    validation_path: Path
    manifest_path: Path
    train_count: int
    validation_count: int
    source_train_files: list[Path]
    source_eval_files: list[Path]
    negative_files: list[Path]
    strict_validation: bool


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def latest_matching_file(directory: Path, pattern: str) -> Path | None:
    matches = [path for path in directory.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name))


def latest_files(directory: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        path = latest_matching_file(directory, pattern)
        if path is not None:
            files.append(path)
    return files


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return openai_quiz_finetune.read_jsonl(path)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    openai_quiz_finetune.write_jsonl(path, records)


def load_env_file(path: Path, *, override: bool = False) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def parse_assistant_ladder(record: dict[str, Any], *, source: Path, line_number: int) -> dict[str, str]:
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError(f"{source}:{line_number} is missing chat messages.")
    assistant_messages = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
    ]
    if not assistant_messages:
        raise ValueError(f"{source}:{line_number} has no assistant message.")
    content = assistant_messages[-1].get("content")
    if not isinstance(content, str):
        raise ValueError(f"{source}:{line_number} assistant content is not text.")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}:{line_number} assistant content is not JSON: {error}") from error
    return daily_map_game.normalize_generated_clue_ladder(payload)


def place_from_record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return {
        "canonical_name": str(metadata.get("place") or ""),
        "place_type": str(metadata.get("place_type") or ""),
        "difficulty": str(metadata.get("difficulty") or ""),
        "acceptable_aliases": [],
    }


def validate_chat_record(
    record: dict[str, Any],
    *,
    source: Path,
    line_number: int,
    strict: bool,
) -> dict[str, Any]:
    if "_negative_" in source.name:
        raise ValueError(f"Negative file cannot be used as SFT input: {source}")
    ladder = parse_assistant_ladder(record, source=source, line_number=line_number)
    if strict:
        critic = daily_map_game.local_map_clue_critique(place_from_record_metadata(record), ladder)
        if not daily_map_game.map_clue_critic_passed(critic):
            raise ValueError(
                f"{source}:{line_number} assistant clue ladder failed map critic: "
                f"{'; '.join(critic.get('failure_reasons') or [])}"
            )
    return record


def validate_sft_records(path: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    records = read_jsonl(path)
    return [
        validate_chat_record(record, source=path, line_number=index, strict=strict)
        for index, record in enumerate(records, start=1)
    ]


def validation_record_from_eval(
    record: dict[str, Any],
    *,
    source: Path,
    line_number: int,
    strict: bool,
) -> dict[str, Any]:
    expected = record.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(f"{source}:{line_number} eval record is missing expected ladder.")
    ladder = daily_map_game.normalize_generated_clue_ladder(expected)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if strict:
        critic = daily_map_game.local_map_clue_critique(
            {
                "canonical_name": str(metadata.get("place") or ""),
                "place_type": str(metadata.get("place_type") or ""),
                "difficulty": str(metadata.get("difficulty") or ""),
                "acceptable_aliases": [],
            },
            ladder,
        )
        if not daily_map_game.map_clue_critic_passed(critic):
            raise ValueError(
                f"{source}:{line_number} expected clue ladder failed map critic: "
                f"{'; '.join(critic.get('failure_reasons') or [])}"
            )
    input_payload = record.get("input") if isinstance(record.get("input"), dict) else {}
    prompt = input_payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{source}:{line_number} eval record has no prompt.")
    system = input_payload.get("system")
    if not isinstance(system, str) or not system.strip():
        system = SYSTEM_MESSAGE
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(ladder, ensure_ascii=True, sort_keys=True)},
        ],
        "metadata": {
            "place": metadata.get("place"),
            "place_type": metadata.get("place_type"),
            "difficulty": metadata.get("difficulty"),
        },
    }


def convert_eval_file(path: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    return [
        validation_record_from_eval(record, source=path, line_number=index, strict=strict)
        for index, record in enumerate(read_jsonl(path), start=1)
    ]


def estimate_payload_bytes(records: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(record, ensure_ascii=True, sort_keys=True).encode("utf-8")) + 1 for record in records)


def prepare_artifacts(
    *,
    training_dir: Path = DEFAULT_TRAINING_DIR,
    out_dir: Path = DEFAULT_TRAINING_DIR,
    train_files: list[Path] | None = None,
    eval_files: list[Path] | None = None,
    negative_files: list[Path] | None = None,
    prefix: str = "openai_map_clue",
    strict: bool = False,
) -> PreparedMapArtifacts:
    train_files = train_files or latest_files(training_dir, DEFAULT_TRAIN_PATTERNS)
    eval_files = eval_files or latest_files(training_dir, DEFAULT_EVAL_PATTERNS)
    negative_files = negative_files or latest_files(training_dir, DEFAULT_NEGATIVE_PATTERNS)
    if not train_files:
        raise ValueError(f"No map clue training files found in {training_dir}.")
    if not eval_files:
        raise ValueError(f"No map clue eval files found in {training_dir}.")

    train_records: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []
    for path in train_files:
        train_records.extend(validate_sft_records(path, strict=strict))
    for path in eval_files:
        validation_records.extend(convert_eval_file(path, strict=strict))

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp()
    train_path = out_dir / f"{prefix}_combined_train_{stamp}.jsonl"
    validation_path = out_dir / f"{prefix}_combined_validation_{stamp}.jsonl"
    manifest_path = out_dir / f"{prefix}_combined_manifest_{stamp}.json"
    write_jsonl(train_path, train_records)
    write_jsonl(validation_path, validation_records)
    manifest = {
        "created_at": now_iso(),
        "train_path": str(train_path),
        "validation_path": str(validation_path),
        "train_count": len(train_records),
        "validation_count": len(validation_records),
        "train_bytes": estimate_payload_bytes(train_records),
        "validation_bytes": estimate_payload_bytes(validation_records),
        "source_train_files": [str(path) for path in train_files],
        "source_eval_files": [str(path) for path in eval_files],
        "negative_files_excluded": [str(path) for path in negative_files],
        "strict_validation": strict,
        "format": "OpenAI chat fine-tuning JSONL for map clue ladders",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return PreparedMapArtifacts(
        train_path=train_path,
        validation_path=validation_path,
        manifest_path=manifest_path,
        train_count=len(train_records),
        validation_count=len(validation_records),
        source_train_files=train_files,
        source_eval_files=eval_files,
        negative_files=negative_files,
        strict_validation=strict,
    )


def registry_run(
    *,
    mode: str,
    artifacts: PreparedMapArtifacts,
    base_model: str | None = None,
    job_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    job = (job_payload or {}).get("job") if isinstance(job_payload, dict) else None
    job = job if isinstance(job, dict) else {}
    return {
        "created_at": now_iso(),
        "kind": "map_clue_fine_tune",
        "mode": mode,
        "base_model": base_model,
        "train_path": str(artifacts.train_path),
        "validation_path": str(artifacts.validation_path),
        "manifest_path": str(artifacts.manifest_path),
        "train_count": artifacts.train_count,
        "validation_count": artifacts.validation_count,
        "source_train_files": [str(path) for path in artifacts.source_train_files],
        "source_eval_files": [str(path) for path in artifacts.source_eval_files],
        "negative_files_excluded": [str(path) for path in artifacts.negative_files],
        "strict_validation": artifacts.strict_validation,
        "training_file_id": (job_payload or {}).get("training_file_id"),
        "validation_file_id": (job_payload or {}).get("validation_file_id"),
        "fine_tuning_job_id": job.get("id"),
        "status": job.get("status", "dry_run" if mode == "dry-run" else None),
        "fine_tuned_model": job.get("fine_tuned_model"),
        "error": error,
        "deployable": False,
    }


def parse_path_list(values: list[Path] | None) -> list[Path] | None:
    if values is None:
        return None
    return [value for value in values]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally launch OpenAI fine-tuning jobs for map clue generation.",
    )
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--train-file", type=Path, action="append")
    parser.add_argument("--eval-file", type=Path, action="append")
    parser.add_argument("--negative-file", type=Path, action="append")
    parser.add_argument("--prefix", default="openai_map_clue")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--override-env", action="store_true")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-model-env", default="OPENAI_MAP_CLUE_FT_BASE_MODEL")
    parser.add_argument("--base-model")
    parser.add_argument("--base-url", default=openai_quiz_finetune.DEFAULT_OPENAI_BASE_URL)
    parser.add_argument("--suffix", default="fultons-map-clues")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument(
        "--critic-strict",
        action="store_true",
        help="Run local map critic validation during artifact prep. Intended for rich source data, not compact SFT JSONL.",
    )
    parser.add_argument("--no-strict", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Validate and combine files without API calls.")
    parser.add_argument("--create-job", action="store_true", help="Upload files and create a fine-tuning job.")
    parser.add_argument("--poll-job", nargs="?", const="", help="Poll a job ID, or latest registry job when omitted.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file, override=args.override_env)
    if args.poll_job is not None:
        job_id = args.poll_job or str(openai_quiz_finetune.latest_registry_run(args.registry).get("fine_tuning_job_id") or "")
        if not job_id:
            raise SystemExit("No fine-tuning job ID supplied or found in registry.")
        client = openai_quiz_finetune.OpenAIClient(
            api_key=openai_quiz_finetune.api_key_from_env(args.api_key_env),
            base_url=args.base_url,
            timeout_sec=args.timeout_sec,
        )
        result = openai_quiz_finetune.poll_job(client=client, job_id=job_id)
        openai_quiz_finetune.append_registry(args.registry, {"created_at": now_iso(), "mode": "poll-job", **result})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    artifacts = prepare_artifacts(
        training_dir=args.training_dir,
        out_dir=args.out_dir,
        train_files=parse_path_list(args.train_file),
        eval_files=parse_path_list(args.eval_file),
        negative_files=parse_path_list(args.negative_file),
        prefix=args.prefix,
        strict=bool(args.critic_strict and not args.no_strict),
    )
    base_model = (args.base_model or os.environ.get(args.base_model_env, "")).strip()
    if args.create_job:
        if not base_model:
            raise SystemExit(f"Base model is required via --base-model or {args.base_model_env}.")
        client = openai_quiz_finetune.OpenAIClient(
            api_key=openai_quiz_finetune.api_key_from_env(args.api_key_env),
            base_url=args.base_url,
            timeout_sec=args.timeout_sec,
        )
        try:
            job_payload = openai_quiz_finetune.create_fine_tune_job(
                client=client,
                artifacts=artifacts,
                base_model=base_model,
                suffix=args.suffix,
            )
            run = registry_run(
                mode="create-job",
                artifacts=artifacts,
                base_model=base_model,
                job_payload=job_payload,
            )
        except Exception as error:
            run = registry_run(
                mode="create-job",
                artifacts=artifacts,
                base_model=base_model,
                error=str(error),
            )
            run["status"] = "failed"
            openai_quiz_finetune.append_registry(args.registry, run)
            print(json.dumps(run, indent=2, ensure_ascii=True))
            return 1
    else:
        run = registry_run(
            mode="dry-run",
            artifacts=artifacts,
            base_model=base_model or None,
        )
    openai_quiz_finetune.append_registry(args.registry, run)
    print(json.dumps(run, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
