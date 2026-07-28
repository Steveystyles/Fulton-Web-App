from __future__ import annotations

import html
import importlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

exporter = importlib.import_module("tools.export_reviewed_football_training_data")
evaluator = importlib.import_module("tools.evaluate_quiz_generator")


ALL_HEADERS = [
    "No.",
    "Original question",
    "Corrected question",
    "Question edit notes",
    "Supplied answer",
    "Answer verification status",
    "Verified/correct answer",
    "Incorrect answer 1",
    "Incorrect answer 2",
    "Incorrect answer 3",
    "Why these are good incorrect answers",
    "Verification/failure note",
    "Verification source",
    "Source URL",
    "Original reasoning",
    "Original score",
    "Original score justification",
]

FAILURE_HEADERS = [
    "No.",
    "Corrected question",
    "Supplied answer",
    "Status",
    "Verified/possible answer(s)",
    "Failure reason",
    "Verification source",
    "Source URL",
]


def xlsx_cell(column: int, row: int, value: object) -> str:
    letters = ""
    column += 1
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    escaped = html.escape(str(value), quote=False)
    return f'<c r="{letters}{row}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def xlsx_sheet(rows: list[list[object]]) -> str:
    rendered_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(xlsx_cell(col_index, row_index, value) for col_index, value in enumerate(row))
        rendered_rows.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rendered_rows)}</sheetData>"
        "</worksheet>"
    )


def write_fixture_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    sheet_entries = []
    rel_entries = []
    content_types = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            sheet_entries.append(
                f'<sheet name="{html.escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            )
            rel_entries.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            content_types.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            workbook.writestr(f"xl/worksheets/sheet{index}.xml", xlsx_sheet(rows))
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(sheet_entries)}</sheets></workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{''.join(rel_entries)}</Relationships>",
        )
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{''.join(content_types)}</Types>",
        )


def all_question_row(
    number: int,
    *,
    question: str,
    status: str = "Confirmed correct",
    answer: str = "Brazil",
    score: str = "8/10",
    missing_distractor: bool = False,
) -> list[object]:
    return [
        number,
        question,
        question,
        "No change required",
        answer,
        status,
        answer,
        "Argentina",
        "" if missing_distractor else "France",
        "Germany",
        "The alternatives are strong teams from the same football context.",
        "Answer confirmed against the listed verification source.",
        "fixture source",
        "https://example.test/source",
        "This is a fair reviewed football question with a clear answer and plausible alternatives.",
        score,
        "Clear with one answer and suitable for a harder quiz slot.",
    ]


class ReviewedFootballTrainingExportTests(unittest.TestCase):
    def test_export_splits_reviewed_workbook_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "reviewed.xlsx"
            write_fixture_xlsx(
                workbook_path,
                {
                    "Summary & Sources": [["summary"]],
                    "All Questions": [
                        ["All reviewed"],
                        ALL_HEADERS,
                        all_question_row(
                            1,
                            question="Which nation won the 1970 FIFA World Cup final in Mexico City?",
                            score="8/10",
                            answer="Brazil",
                        ),
                        all_question_row(
                            5,
                            question="Which nation won the 1966 FIFA World Cup final at Wembley?",
                            score="9/10",
                            answer="England",
                        ),
                        all_question_row(
                            6,
                            question="Which club won the 2005 UEFA Champions League final in Istanbul?",
                            score="6/10",
                            answer="Liverpool",
                        ),
                        all_question_row(
                            7,
                            question="Which club won a routine league match on a specific date in 2019?",
                            score="2/10",
                            answer="Arsenal",
                        ),
                        all_question_row(
                            8,
                            question="Which country hosted the 1998 FIFA World Cup tournament?",
                            score="8/10",
                            answer="France",
                            missing_distractor=True,
                        ),
                        all_question_row(
                            9,
                            question="Which nation won the 1970 FIFA World Cup final in Mexico City?",
                            score="8/10",
                            answer="Brazil",
                        ),
                    ],
                    "Confirmed Quiz": [["confirmed"]],
                    "Failures": [
                        ["Failures"],
                        FAILURE_HEADERS,
                        [
                            10,
                            "In which minute did a player score twice in the same match?",
                            "54",
                            "Ambiguous",
                            "54; 77",
                            "Question is under-specified because more than one goal fits.",
                            "fixture source",
                            "https://example.test/source",
                        ],
                    ],
                },
            )

            result = exporter.export_reviewed_football_training_data(
                workbook_path,
                Path(tmpdir) / "out",
                prefix="fixture_review",
            )
            train_records = [
                json.loads(line)
                for line in result.train_path.read_text(encoding="utf-8").splitlines()
            ]
            eval_records = [
                json.loads(line)
                for line in result.eval_path.read_text(encoding="utf-8").splitlines()
            ]
            negative_records = [
                json.loads(line)
                for line in result.negative_path.read_text(encoding="utf-8").splitlines()
            ]
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.train_count, 1)
        self.assertEqual(result.eval_count, 1)
        self.assertEqual(result.negative_count, 2)
        self.assertEqual(result.medium_quality_count, 1)
        self.assertEqual(result.skipped_counts["missing_core_fields"], 1)
        self.assertEqual(result.skipped_counts["duplicate_questions"], 1)
        self.assertEqual(manifest["score_distribution"]["8/10"], 3)

        train_question = json.loads(train_records[0]["messages"][2]["content"])
        self.assertEqual(train_question["difficulty"], "hard")
        self.assertEqual(train_question["correct_answer"], "Brazil")
        self.assertEqual(eval_records[0]["expected_output"]["difficulty"], "medium")
        self.assertEqual(eval_records[0]["metadata"]["workbook_no"], 5)
        self.assertEqual(
            {record["metadata"]["reason"] for record in negative_records},
            {"review_failure", "low_review_score"},
        )

    def test_exported_eval_records_work_with_fixture_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "reviewed.xlsx"
            write_fixture_xlsx(
                workbook_path,
                {
                    "All Questions": [
                        ["All reviewed"],
                        ALL_HEADERS,
                        all_question_row(
                            5,
                            question="Which nation won the 1966 FIFA World Cup final at Wembley?",
                            score="9/10",
                            answer="England",
                        ),
                    ],
                    "Failures": [
                        ["Failures"],
                        FAILURE_HEADERS,
                    ],
                },
            )

            result = exporter.export_reviewed_football_training_data(
                workbook_path,
                Path(tmpdir) / "out",
                prefix="fixture_review",
            )
            eval_records = [
                json.loads(line)
                for line in result.eval_path.read_text(encoding="utf-8").splitlines()
            ]

        report = evaluator.evaluate_records(
            eval_records,
            evaluator.FixtureExpectedGenerator(),
        )

        self.assertEqual(report["metrics"]["total"], 1)
        self.assertEqual(report["metrics"]["publishable"], 1)
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main()
