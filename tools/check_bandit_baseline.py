#!/usr/bin/env python3
"""Compare Bandit JSON with the repository's exact-site reviewed allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SUPPORTED_BANDIT_VERSION = "1.9.4"
BASELINE_KEYS = frozenset(
    {"schema_version", "bandit_version", "scanned_files", "findings"}
)
FINDING_KEYS = frozenset(
    {
        "filename",
        "test_id",
        "test_name",
        "issue_severity",
        "issue_confidence",
        "issue_text",
        "cwe_id",
        "line_number",
        "line_range",
        "col_offset",
        "end_col_offset",
        "code_sha256",
    }
)
LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "UNDEFINED"})
TEST_ID_PATTERN = re.compile(r"B[0-9]{3}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
WINDOWS_DRIVE_PATTERN = re.compile(r"[A-Za-z]:")


class ValidationError(ValueError):
    """Raised when either input cannot be compared safely."""


@dataclass(frozen=True, order=True)
class FindingIdentity:
    filename: str
    test_id: str
    test_name: str
    issue_severity: str
    issue_confidence: str
    issue_text: str
    cwe_id: int
    line_number: int
    line_range: tuple[int, ...]
    col_offset: int
    end_col_offset: int
    code_sha256: str


@dataclass(frozen=True)
class ComparisonResult:
    baseline_count: int
    current_count: int
    resolved_count: int
    required_file_count: int
    scanned_file_count: int
    unexpected: tuple[tuple[FindingIdentity, int], ...]


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_json_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            detail = str(exc)
        else:
            detail = f"{type(exc).__name__}: {exc}"
        raise ValidationError(f"cannot read {path}: {detail}") from exc


def normalize_filename(value: Any, field: str = "filename") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise ValidationError(f"{field} contains a NUL byte")

    candidate = value.replace("\\", "/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    if candidate.startswith("/") or WINDOWS_DRIVE_PATTERN.match(candidate):
        raise ValidationError(f"{field} must be repository-relative: {value!r}")

    parts: list[str] = []
    for part in candidate.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValidationError(f"{field} must not escape the repository: {value!r}")
        parts.append(part)
    if not parts:
        raise ValidationError(f"{field} does not identify a file")
    return "/".join(parts)


def fingerprint_code(code: str) -> str:
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], field: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise ValidationError(f"{field} has invalid fields ({'; '.join(details)})")


def _require_string(value: Any, field: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        raise ValidationError(f"{field} must be a {qualifier}string")
    return value


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _require_level(value: Any, field: str) -> str:
    level = _require_string(value, field)
    if level not in LEVELS:
        raise ValidationError(f"{field} is not a recognized Bandit level: {level!r}")
    return level


def _require_line_range(value: Any, field: str, line_number: int) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty array")
    lines = tuple(
        _require_int(line, f"{field}[{index}]", minimum=1)
        for index, line in enumerate(value)
    )
    if lines != tuple(sorted(set(lines))):
        raise ValidationError(f"{field} must contain unique, ascending line numbers")
    if line_number not in lines:
        raise ValidationError(f"{field} must contain line_number")
    return lines


def _identity_from_baseline(value: Any, index: int) -> FindingIdentity:
    field = f"baseline.findings[{index}]"
    finding = _require_mapping(value, field)
    _require_exact_keys(finding, FINDING_KEYS, field)

    line_number = _require_int(finding["line_number"], f"{field}.line_number", minimum=1)
    test_id = _require_string(finding["test_id"], f"{field}.test_id")
    if not TEST_ID_PATTERN.fullmatch(test_id):
        raise ValidationError(f"{field}.test_id is invalid: {test_id!r}")
    code_sha256 = _require_string(finding["code_sha256"], f"{field}.code_sha256")
    if not SHA256_PATTERN.fullmatch(code_sha256):
        raise ValidationError(f"{field}.code_sha256 must be a lowercase SHA-256 digest")

    return FindingIdentity(
        filename=normalize_filename(finding["filename"], f"{field}.filename"),
        test_id=test_id,
        test_name=_require_string(finding["test_name"], f"{field}.test_name"),
        issue_severity=_require_level(
            finding["issue_severity"], f"{field}.issue_severity"
        ),
        issue_confidence=_require_level(
            finding["issue_confidence"], f"{field}.issue_confidence"
        ),
        issue_text=_require_string(finding["issue_text"], f"{field}.issue_text"),
        cwe_id=_require_int(finding["cwe_id"], f"{field}.cwe_id", minimum=1),
        line_number=line_number,
        line_range=_require_line_range(
            finding["line_range"], f"{field}.line_range", line_number
        ),
        col_offset=_require_int(finding["col_offset"], f"{field}.col_offset"),
        end_col_offset=_require_int(
            finding["end_col_offset"], f"{field}.end_col_offset"
        ),
        code_sha256=code_sha256,
    )


def _identity_from_current(value: Any, index: int) -> FindingIdentity:
    field = f"current.results[{index}]"
    finding = _require_mapping(value, field)
    line_number = _require_int(finding.get("line_number"), f"{field}.line_number", minimum=1)
    test_id = _require_string(finding.get("test_id"), f"{field}.test_id")
    if not TEST_ID_PATTERN.fullmatch(test_id):
        raise ValidationError(f"{field}.test_id is invalid: {test_id!r}")
    cwe = _require_mapping(finding.get("issue_cwe"), f"{field}.issue_cwe")
    code = _require_string(finding.get("code"), f"{field}.code", nonempty=False)

    return FindingIdentity(
        filename=normalize_filename(finding.get("filename"), f"{field}.filename"),
        test_id=test_id,
        test_name=_require_string(finding.get("test_name"), f"{field}.test_name"),
        issue_severity=_require_level(
            finding.get("issue_severity"), f"{field}.issue_severity"
        ),
        issue_confidence=_require_level(
            finding.get("issue_confidence"), f"{field}.issue_confidence"
        ),
        issue_text=_require_string(finding.get("issue_text"), f"{field}.issue_text"),
        cwe_id=_require_int(cwe.get("id"), f"{field}.issue_cwe.id", minimum=1),
        line_number=line_number,
        line_range=_require_line_range(
            finding.get("line_range"), f"{field}.line_range", line_number
        ),
        col_offset=_require_int(finding.get("col_offset"), f"{field}.col_offset"),
        end_col_offset=_require_int(
            finding.get("end_col_offset"), f"{field}.end_col_offset"
        ),
        code_sha256=fingerprint_code(code),
    )


def _parse_baseline_files(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValidationError("baseline.scanned_files must be a non-empty array")
    files = tuple(
        normalize_filename(filename, f"baseline.scanned_files[{index}]")
        for index, filename in enumerate(value)
    )
    if len(files) != len(set(files)):
        raise ValidationError(
            "baseline.scanned_files contains duplicate normalized paths"
        )
    if files != tuple(sorted(files)):
        raise ValidationError(
            "baseline.scanned_files must be sorted by normalized path"
        )
    return files


def _parse_current_files(value: Any) -> tuple[str, ...]:
    metrics = _require_mapping(value, "current report.metrics")
    files = tuple(
        normalize_filename(filename, f"current report.metrics key {filename!r}")
        for filename in metrics
        if filename != "_totals"
    )
    if not files:
        raise ValidationError("current report.metrics contains no scanned files")
    if len(files) != len(set(files)):
        raise ValidationError(
            "current report.metrics contains duplicate normalized file paths"
        )
    return files


def _site_key(
    identity: FindingIdentity,
) -> tuple[str, str, int, tuple[int, ...], int, int]:
    return (
        identity.filename,
        identity.test_id,
        identity.line_number,
        identity.line_range,
        identity.col_offset,
        identity.end_col_offset,
    )


def parse_baseline(
    report: Any,
) -> tuple[tuple[FindingIdentity, ...], tuple[str, ...]]:
    baseline = _require_mapping(report, "baseline")
    _require_exact_keys(baseline, BASELINE_KEYS, "baseline")
    if (
        type(baseline["schema_version"]) is not int
        or baseline["schema_version"] != SCHEMA_VERSION
    ):
        raise ValidationError(
            f"baseline.schema_version must be the integer {SCHEMA_VERSION}"
        )
    if baseline["bandit_version"] != SUPPORTED_BANDIT_VERSION:
        raise ValidationError(
            "baseline.bandit_version must be "
            f"{SUPPORTED_BANDIT_VERSION!r}, got {baseline['bandit_version']!r}"
        )
    findings = baseline["findings"]
    if not isinstance(findings, list):
        raise ValidationError("baseline.findings must be an array")
    scanned_files = _parse_baseline_files(baseline["scanned_files"])

    identities = tuple(
        _identity_from_baseline(finding, index)
        for index, finding in enumerate(findings)
    )
    first_by_site: dict[tuple[str, str, int, tuple[int, ...], int, int], FindingIdentity] = {}
    duplicate_sites: list[FindingIdentity] = []
    for identity in identities:
        site = _site_key(identity)
        if site in first_by_site:
            duplicate_sites.append(identity)
        else:
            first_by_site[site] = identity
    if duplicate_sites:
        locations = ", ".join(
            format_identity(identity) for identity in sorted(duplicate_sites)
        )
        raise ValidationError(f"baseline contains duplicate finding sites: {locations}")

    uncovered = sorted({identity.filename for identity in identities} - set(scanned_files))
    if uncovered:
        raise ValidationError(
            "baseline findings are missing from scanned_files: " + ", ".join(uncovered)
        )
    return identities, scanned_files


def parse_current(
    report: Any,
) -> tuple[tuple[FindingIdentity, ...], tuple[str, ...]]:
    current = _require_mapping(report, "current report")
    errors = current.get("errors")
    if not isinstance(errors, list):
        raise ValidationError("current report.errors must be an array")
    if errors:
        raise ValidationError(
            f"Bandit reported {len(errors)} scan error(s); comparison is unsafe"
        )
    results = current.get("results")
    if not isinstance(results, list):
        raise ValidationError("current report.results must be an array")
    scanned_files = _parse_current_files(current.get("metrics"))
    identities = tuple(
        _identity_from_current(finding, index)
        for index, finding in enumerate(results)
    )
    unscanned_results = sorted(
        {identity.filename for identity in identities} - set(scanned_files)
    )
    if unscanned_results:
        raise ValidationError(
            "current findings are missing from metrics: " + ", ".join(unscanned_results)
        )
    return identities, scanned_files


def compare_reports(baseline_report: Any, current_report: Any) -> ComparisonResult:
    baseline, required_files = parse_baseline(baseline_report)
    current, scanned_files = parse_current(current_report)
    missing_files = sorted(set(required_files) - set(scanned_files))
    if missing_files:
        raise ValidationError(
            "Bandit did not scan required file(s): " + ", ".join(missing_files)
        )
    baseline_counts = Counter(baseline)
    current_counts = Counter(current)
    unexpected_counts = current_counts - baseline_counts
    matched_count = sum((current_counts & baseline_counts).values())
    return ComparisonResult(
        baseline_count=len(baseline),
        current_count=len(current),
        resolved_count=len(baseline) - matched_count,
        required_file_count=len(required_files),
        scanned_file_count=len(scanned_files),
        unexpected=tuple(sorted(unexpected_counts.items())),
    )


def format_identity(identity: FindingIdentity) -> str:
    return (
        f"{identity.filename}:{identity.line_number} "
        f"{identity.test_id}/{identity.test_name} "
        f"[{identity.issue_severity}/{identity.issue_confidence}, "
        f"CWE-{identity.cwe_id}] {identity.issue_text!r} "
        f"(code {identity.code_sha256[:12]})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail unless every current Bandit finding matches one exact reviewed "
            "baseline site. Resolved baseline findings are allowed."
        )
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        result = compare_reports(load_json(args.baseline), load_json(args.current))
    except ValidationError as exc:
        print(f"Bandit baseline comparison failed closed: {exc}", file=sys.stderr)
        return 1

    if result.unexpected:
        extra_count = sum(count for _, count in result.unexpected)
        print(
            "Bandit baseline comparison rejected "
            f"{extra_count} unreviewed finding occurrence(s):",
            file=sys.stderr,
        )
        for identity, count in result.unexpected:
            suffix = f" x{count}" if count > 1 else ""
            print(f"- {format_identity(identity)}{suffix}", file=sys.stderr)
        return 1

    print(
        "Bandit baseline comparison passed: "
        f"{result.current_count} current, {result.resolved_count} resolved, "
        f"{result.baseline_count} reviewed finding(s); "
        f"{result.scanned_file_count} file(s) scanned, "
        f"{result.required_file_count} required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
