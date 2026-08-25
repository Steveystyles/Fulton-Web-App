from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
COMPARATOR_PATH = PROJECT_DIR / "tools" / "check_bandit_baseline.py"
SPEC = importlib.util.spec_from_file_location("check_bandit_baseline", COMPARATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
comparator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comparator
SPEC.loader.exec_module(comparator)


def current_finding(
    *,
    filename: str = "./server.py",
    line_number: int = 10,
    code: str | None = None,
) -> dict[str, object]:
    if code is None:
        code = f"{line_number} response = urlopen(request)\n"
    return {
        "code": code,
        "col_offset": 15,
        "end_col_offset": 31,
        "filename": filename,
        "issue_confidence": "HIGH",
        "issue_cwe": {"id": 22, "link": "https://cwe.mitre.org/data/definitions/22.html"},
        "issue_severity": "MEDIUM",
        "issue_text": (
            "Audit url open for permitted schemes. Allowing use of file:/ or "
            "custom schemes is often unexpected."
        ),
        "line_number": line_number,
        "line_range": [line_number],
        "more_info": "https://bandit.readthedocs.io/",
        "test_id": "B310",
        "test_name": "blacklist",
    }


def baseline_finding(current: dict[str, object]) -> dict[str, object]:
    cwe = current["issue_cwe"]
    assert isinstance(cwe, dict)
    code = current["code"]
    assert isinstance(code, str)
    return {
        "filename": current["filename"],
        "test_id": current["test_id"],
        "test_name": current["test_name"],
        "issue_severity": current["issue_severity"],
        "issue_confidence": current["issue_confidence"],
        "issue_text": current["issue_text"],
        "cwe_id": cwe["id"],
        "line_number": current["line_number"],
        "line_range": current["line_range"],
        "col_offset": current["col_offset"],
        "end_col_offset": current["end_col_offset"],
        "code_sha256": comparator.fingerprint_code(code),
    }


def baseline_report(
    *findings: dict[str, object],
    scanned_files: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    if scanned_files is None:
        scanned_files = sorted(
            {
                comparator.normalize_filename(finding["filename"])
                for finding in findings
            }
            or {"server.py"}
        )
    return {
        "schema_version": 1,
        "bandit_version": "1.9.4",
        "scanned_files": list(scanned_files),
        "findings": list(findings),
    }


def current_report(
    *findings: dict[str, object],
    scanned_files: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    if scanned_files is None:
        scanned_files = sorted(
            {str(finding["filename"]) for finding in findings} or {"server.py"}
        )
    return {
        "errors": [],
        "generated_at": "2026-08-24T00:00:00Z",
        "metrics": {
            filename: {"future_metric_metadata": True} for filename in scanned_files
        },
        "results": list(findings),
    }


class BanditBaselineComparatorTests(unittest.TestCase):
    def test_rejects_absolute_traversal_and_mixed_root_paths(self) -> None:
        invalid_paths = [
            "/server.py",
            "C:\\server.py",
            "./C:/server.py",
            "../server.py",
            r"./\server.py",
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaises(comparator.ValidationError):
                    comparator.normalize_filename(path)

    def test_normalizes_paths_and_newlines_without_rejecting_future_metadata(self) -> None:
        current = current_finding(
            filename="./tools/check.py",
            code="10 response = urlopen(request)\n",
        )
        current["future_result_metadata"] = {"added": "later"}
        baseline_source = copy.deepcopy(current)
        baseline_source["filename"] = ".\\tools\\check.py"
        baseline_source["code"] = "10 response = urlopen(request)\r\n"

        result = comparator.compare_reports(
            baseline_report(baseline_finding(baseline_source)),
            current_report(current),
        )

        self.assertEqual(result.current_count, 1)
        self.assertEqual(result.resolved_count, 0)
        self.assertEqual(result.unexpected, ())

    def test_resolved_findings_may_disappear(self) -> None:
        retained = current_finding(line_number=10)
        resolved = current_finding(line_number=20)

        result = comparator.compare_reports(
            baseline_report(baseline_finding(retained), baseline_finding(resolved)),
            current_report(retained),
        )

        self.assertEqual(result.resolved_count, 1)
        self.assertEqual(result.unexpected, ())

    def test_new_shifted_and_duplicate_current_occurrences_fail(self) -> None:
        reviewed = current_finding(line_number=10)
        baseline = baseline_report(baseline_finding(reviewed))
        cases = {
            "new": current_report(reviewed, current_finding(line_number=30)),
            "shifted": current_report(current_finding(line_number=11)),
            "duplicate": current_report(reviewed, copy.deepcopy(reviewed)),
        }

        for name, report in cases.items():
            with self.subTest(name=name):
                result = comparator.compare_reports(baseline, report)
                self.assertTrue(result.unexpected)
                self.assertGreaterEqual(sum(count for _, count in result.unexpected), 1)

    def test_duplicate_baseline_sites_fail_even_when_metadata_differs(self) -> None:
        current = current_finding(filename="./server.py")
        first = baseline_finding(current)
        second = copy.deepcopy(first)
        second["filename"] = ".\\server.py"
        second["code_sha256"] = "0" * 64

        with self.assertRaisesRegex(comparator.ValidationError, "duplicate finding site"):
            comparator.compare_reports(
                baseline_report(first, second),
                current_report(current),
            )

    def test_required_scanned_file_coverage_is_fail_closed_but_allows_extras(self) -> None:
        current = current_finding(filename="./server.py")
        baseline = baseline_report(
            baseline_finding(current),
            scanned_files=["server.py", "tools/worker.py"],
        )

        result = comparator.compare_reports(
            baseline,
            current_report(
                current,
                scanned_files=["./server.py", "./tools/worker.py", "./new.py"],
            ),
        )
        self.assertEqual(result.required_file_count, 2)
        self.assertEqual(result.scanned_file_count, 3)

        malformed_reports = [
            {"errors": [], "results": [current]},
            {"errors": [], "metrics": {}, "results": [current]},
            current_report(current, scanned_files=["./server.py"]),
            current_report(
                current,
                scanned_files=["./server.py", ".\\server.py", "./tools/worker.py"],
            ),
        ]
        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(comparator.ValidationError):
                    comparator.compare_reports(baseline, report)

    def test_malformed_missing_or_unknown_baseline_data_fails_closed(self) -> None:
        current = current_finding()
        malformed_reports = [
            {"schema_version": 1, "bandit_version": "1.9.4"},
            {
                "schema_version": 1.0,
                "bandit_version": "1.9.4",
                "scanned_files": ["server.py"],
                "findings": [],
            },
            {
                "schema_version": 1,
                "bandit_version": "1.9.4",
                "scanned_files": ["server.py"],
                "findings": [{"filename": "server.py"}],
            },
            {
                "schema_version": 1,
                "bandit_version": "1.9.4",
                "scanned_files": ["server.py"],
                "findings": [],
                "unreviewed_field": True,
            },
        ]
        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(comparator.ValidationError):
                    comparator.compare_reports(report, current_report(current))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(comparator.ValidationError):
                comparator.load_json(root / "missing.json")

            duplicate_keys = root / "duplicate-keys.json"
            duplicate_keys.write_text(
                '{"schema_version":1,"schema_version":1,"bandit_version":"1.9.4",'
                '"scanned_files":["server.py"],"findings":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(comparator.ValidationError, "duplicate JSON key"):
                comparator.load_json(duplicate_keys)

    def test_missing_results_scanner_errors_and_malformed_results_fail_closed(self) -> None:
        baseline = baseline_report()
        malformed_reports = [
            {"errors": []},
            {
                "errors": [{"filename": "broken.py", "reason": "parse failed"}],
                "metrics": {"server.py": {}},
                "results": [],
            },
            {
                "errors": [],
                "metrics": {"server.py": {}},
                "results": [{"filename": "server.py"}],
            },
        ]
        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(comparator.ValidationError):
                    comparator.compare_reports(baseline, report)

    def test_cli_returns_nonzero_for_unreviewed_or_missing_inputs(self) -> None:
        reviewed = current_finding()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline_path = root / "baseline.json"
            current_path = root / "current.json"
            baseline_path.write_text(
                json.dumps(baseline_report(baseline_finding(reviewed))),
                encoding="utf-8",
            )
            current_path.write_text(
                json.dumps(current_report(reviewed, current_finding(line_number=40))),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(
                    comparator.main(
                        [
                            "--baseline",
                            str(baseline_path),
                            "--current",
                            str(current_path),
                        ]
                    ),
                    1,
                )
                self.assertEqual(
                    comparator.main(
                        [
                            "--baseline",
                            str(root / "missing.json"),
                            "--current",
                            str(current_path),
                        ]
                    ),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
