from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz

DEFAULT_TRAIN_PATTERNS = (
    "quiz_sft_train_*.jsonl",
    "prod_quiz_sft_train_*.jsonl",
    "football_review_sft_train_*.jsonl",
)
DEFAULT_EVAL_PATTERNS = (
    "quiz_eval_*.jsonl",
    "prod_quiz_eval_*.jsonl",
    "football_review_eval_*.jsonl",
)
DEFAULT_NEGATIVE_PATTERNS = ("football_review_negative_*.jsonl",)
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_REGISTRY_PATH = DEFAULT_TRAINING_DIR / "model_registry.json"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."


@dataclass(frozen=True)
class PreparedArtifacts:
    train_path: Path
    validation_path: Path
    manifest_path: Path
    train_count: int
    validation_count: int
    source_train_files: list[Path]
    source_eval_files: list[Path]
    negative_files: list[Path]


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
        match = latest_matching_file(directory, pattern)
        if match is not None:
            files.append(match)
    return files


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object.")
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def assistant_question_from_messages(record: dict[str, Any], *, source: Path, line_number: int) -> dict[str, Any]:
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError(f"{source}:{line_number} is missing chat messages.")
    assistant_messages = [
        message for message in messages if isinstance(message, dict) and message.get("role") == "assistant"
    ]
    if not assistant_messages:
        raise ValueError(f"{source}:{line_number} has no assistant message.")
    content = assistant_messages[-1].get("content")
    if not isinstance(content, str):
        raise ValueError(f"{source}:{line_number} assistant content is not text.")
    try:
        question = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}:{line_number} assistant content is not JSON: {error}") from error
    validation = daily_quiz.validate_question(question)
    if not validation.passed:
        raise ValueError(f"{source}:{line_number} assistant question is invalid: {validation.reason}")
    return validation.question or question


def validate_sft_records(path: Path) -> list[dict[str, Any]]:
    if "_negative_" in path.name:
        raise ValueError(f"Negative file cannot be used as SFT input: {path}")
    records = read_jsonl(path)
    for index, record in enumerate(records, start=1):
        assistant_question_from_messages(record, source=path, line_number=index)
    return records


def validation_record_from_eval(record: dict[str, Any], *, source: Path, line_number: int) -> dict[str, Any]:
    expected = record.get("expected_output")
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    subject = str(context.get("subject") or metadata.get("subject") or "")
    difficulty = str(context.get("difficulty") or metadata.get("difficulty") or "")
    validation = daily_quiz.validate_question(
        expected,
        expected_subject=subject or None,
        expected_difficulty=difficulty or None,
    )
    if not validation.passed or validation.question is None:
        raise ValueError(f"{source}:{line_number} expected output is invalid: {validation.reason}")

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
            {
                "role": "assistant",
                "content": json.dumps(validation.question, ensure_ascii=True, sort_keys=True),
            },
        ]
    }


def convert_eval_file(path: Path) -> list[dict[str, Any]]:
    return [
        validation_record_from_eval(record, source=path, line_number=index)
        for index, record in enumerate(read_jsonl(path), start=1)
    ]


def prepare_artifacts(
    *,
    training_dir: Path = DEFAULT_TRAINING_DIR,
    out_dir: Path = DEFAULT_TRAINING_DIR,
    train_files: list[Path] | None = None,
    eval_files: list[Path] | None = None,
    negative_files: list[Path] | None = None,
    prefix: str = "openai_quiz",
) -> PreparedArtifacts:
    train_files = train_files or latest_files(training_dir, DEFAULT_TRAIN_PATTERNS)
    eval_files = eval_files or latest_files(training_dir, DEFAULT_EVAL_PATTERNS)
    negative_files = negative_files or latest_files(training_dir, DEFAULT_NEGATIVE_PATTERNS)
    if not train_files:
        raise ValueError(f"No training files found in {training_dir}.")
    if not eval_files:
        raise ValueError(f"No eval files found in {training_dir}.")

    train_records: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []
    for path in train_files:
        train_records.extend(validate_sft_records(path))
    for path in eval_files:
        validation_records.extend(convert_eval_file(path))

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
        "source_train_files": [str(path) for path in train_files],
        "source_eval_files": [str(path) for path in eval_files],
        "negative_files_excluded": [str(path) for path in negative_files],
        "format": "OpenAI chat fine-tuning JSONL",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return PreparedArtifacts(
        train_path=train_path,
        validation_path=validation_path,
        manifest_path=manifest_path,
        train_count=len(train_records),
        validation_count=len(validation_records),
        source_train_files=train_files,
        source_eval_files=eval_files,
        negative_files=negative_files,
    )


def read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"runs": []}
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError(f"Registry is not a JSON object: {path}")
    runs = registry.get("runs")
    if not isinstance(runs, list):
        registry["runs"] = []
    return registry


def append_registry(path: Path, run: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = read_registry(path)
    registry["runs"].append(run)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=True), encoding="utf-8")


def latest_registry_run(path: Path) -> dict[str, Any]:
    registry = read_registry(path)
    runs = registry.get("runs", [])
    if not runs:
        raise ValueError(f"No runs found in registry: {path}")
    return runs[-1]


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        timeout_sec: int = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
        }

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"OpenAI request failed with HTTP {error.code}: {detail}") from error
        if not isinstance(payload, dict):
            raise ValueError("OpenAI response was not a JSON object.")
        return payload

    def post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        return self._request_json(request)

    def get_json(self, endpoint: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            headers=self._headers(),
            method="GET",
        )
        return self._request_json(request)

    def upload_file(self, path: Path, *, purpose: str = "fine-tune") -> dict[str, Any]:
        boundary = f"----fultons-{secrets.token_hex(12)}"
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks = [
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="purpose"\r\n\r\n'
                f"{purpose}\r\n"
            ).encode("utf-8"),
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8"),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
        request = urllib.request.Request(
            f"{self.base_url}/files",
            data=b"".join(chunks),
            headers=self._headers(f"multipart/form-data; boundary={boundary}"),
            method="POST",
        )
        return self._request_json(request)


def api_key_from_env(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise ValueError(f"{env_name} is not configured.")
    return value


def create_fine_tune_job(
    *,
    client: OpenAIClient,
    artifacts: PreparedArtifacts,
    base_model: str,
    suffix: str | None = None,
) -> dict[str, Any]:
    training_file = client.upload_file(artifacts.train_path)
    validation_file = client.upload_file(artifacts.validation_path)
    training_file_id = str(training_file.get("id") or "")
    validation_file_id = str(validation_file.get("id") or "")
    if not training_file_id or not validation_file_id:
        raise ValueError("OpenAI file upload response did not include file IDs.")
    payload: dict[str, Any] = {
        "training_file": training_file_id,
        "validation_file": validation_file_id,
        "model": base_model,
    }
    if suffix:
        payload["suffix"] = suffix
    job = client.post_json("/fine_tuning/jobs", payload)
    if not job.get("id"):
        raise ValueError("OpenAI fine-tuning job response did not include a job ID.")
    return {
        "training_file_id": training_file_id,
        "validation_file_id": validation_file_id,
        "job": job,
    }


def registry_run(
    *,
    mode: str,
    artifacts: PreparedArtifacts,
    base_model: str | None = None,
    job_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    job = (job_payload or {}).get("job") if isinstance(job_payload, dict) else None
    job = job if isinstance(job, dict) else {}
    return {
        "created_at": now_iso(),
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
        "training_file_id": (job_payload or {}).get("training_file_id"),
        "validation_file_id": (job_payload or {}).get("validation_file_id"),
        "fine_tuning_job_id": job.get("id"),
        "status": job.get("status", "dry_run" if mode == "dry-run" else None),
        "fine_tuned_model": job.get("fine_tuned_model"),
        "error": error,
        "deployable": False,
    }


def poll_job(*, client: OpenAIClient, job_id: str) -> dict[str, Any]:
    job = client.get_json(f"/fine_tuning/jobs/{job_id}")
    return {
        "polled_at": now_iso(),
        "fine_tuning_job_id": job.get("id", job_id),
        "status": job.get("status"),
        "fine_tuned_model": job.get("fine_tuned_model"),
        "raw_job": job,
    }


def parse_path_list(values: list[Path] | None) -> list[Path] | None:
    if values is None:
        return None
    return [value for value in values]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally launch OpenAI fine-tuning jobs for quiz generation.",
    )
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--train-file", type=Path, action="append")
    parser.add_argument("--eval-file", type=Path, action="append")
    parser.add_argument("--negative-file", type=Path, action="append")
    parser.add_argument("--prefix", default="openai_quiz")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-model-env", default="OPENAI_FT_BASE_MODEL")
    parser.add_argument("--base-model")
    parser.add_argument("--base-url", default=DEFAULT_OPENAI_BASE_URL)
    parser.add_argument("--suffix", default="fultons-quiz")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", help="Validate and combine files without API calls.")
    parser.add_argument("--create-job", action="store_true", help="Upload files and create a fine-tuning job.")
    parser.add_argument("--poll-job", nargs="?", const="", help="Poll a job ID, or latest registry job when omitted.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.poll_job is not None:
        job_id = args.poll_job or str(latest_registry_run(args.registry).get("fine_tuning_job_id") or "")
        if not job_id:
            raise SystemExit("No fine-tuning job ID supplied or found in registry.")
        client = OpenAIClient(
            api_key=api_key_from_env(args.api_key_env),
            base_url=args.base_url,
            timeout_sec=args.timeout_sec,
        )
        result = poll_job(client=client, job_id=job_id)
        append_registry(args.registry, {"created_at": now_iso(), "mode": "poll-job", **result})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    artifacts = prepare_artifacts(
        training_dir=args.training_dir,
        out_dir=args.out_dir,
        train_files=parse_path_list(args.train_file),
        eval_files=parse_path_list(args.eval_file),
        negative_files=parse_path_list(args.negative_file),
        prefix=args.prefix,
    )

    base_model = (args.base_model or os.environ.get(args.base_model_env, "")).strip()
    if args.create_job:
        if not base_model:
            raise SystemExit(f"Base model is required via --base-model or {args.base_model_env}.")
        client = OpenAIClient(
            api_key=api_key_from_env(args.api_key_env),
            base_url=args.base_url,
            timeout_sec=args.timeout_sec,
        )
        try:
            job_payload = create_fine_tune_job(
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
            append_registry(args.registry, run)
            print(json.dumps(run, indent=2, ensure_ascii=True))
            return 1
    else:
        run = registry_run(
            mode="dry-run",
            artifacts=artifacts,
            base_model=base_model or None,
        )
    append_registry(args.registry, run)
    print(json.dumps(run, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
