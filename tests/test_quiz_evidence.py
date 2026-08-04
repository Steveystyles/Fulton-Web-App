from __future__ import annotations

import unittest

import quiz_evidence


def evidence_item(
    text: str,
    *,
    host: str,
    tier: str,
    path: str,
) -> dict[str, str]:
    return {
        "title": text,
        "source_name": host,
        "source_url": f"https://{host}/{path}",
        "tier": tier,
        "snippet": text,
        "excerpt": text,
        "query": "test query",
    }


class QuizEvidenceTests(unittest.TestCase):
    def test_openrouter_annotations_are_normalized_as_evidence(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": "https://www.fifa.com/history/five-titles",
                                    "title": "Brazil's five titles",
                                    "content": "Brazil became the first nation to win five World Cups in 2002.",
                                },
                            },
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": "https://www.bbc.co.uk/sport/archive/brazil-2002",
                                    "title": "Brazil crowned champions",
                                    "content": "Brazil won its fifth World Cup title in the 2002 final.",
                                },
                            },
                        ]
                    }
                }
            ]
        }

        evidence = quiz_evidence.openrouter_response_evidence(
            payload,
            timeout_sec=5,
            query="Brazil five World Cups",
        )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["tier"], "primary")
        self.assertEqual(evidence[1]["tier"], "reputable")

    def test_ordinary_claim_can_pass_with_one_explicit_source(self) -> None:
        question = {
            "question": "Which instrument has keys, pedals, and strings struck by felt-covered hammers?",
            "correct_answer": "Piano",
            "explanation": "A piano uses hammers to strike strings when its keys are pressed.",
            "interesting_reason": "Its mechanism combines features of string and percussion instruments.",
            "tags": ["music", "instruments"],
        }
        evidence = [
            evidence_item(
                "A piano produces sound when felt-covered hammers strike its strings as keys are pressed.",
                host="britannica.com",
                tier="reputable",
                path="art/piano",
            )
        ]

        result = quiz_evidence.precheck_question_evidence(question, evidence)

        self.assertTrue(result["passed"])
        self.assertFalse(result["risk_profile"]["high_risk"])

    def test_descriptive_answer_can_match_explicit_source_paraphrases(self) -> None:
        question = {
            "question": "In the early days of cinema, what was the primary purpose of intertitles?",
            "correct_answer": "To provide dialogue and narrative context",
            "explanation": (
                "Before synchronized sound was introduced in the late 1920s, silent films "
                "relied on intertitles to convey dialogue and explain plot points."
            ),
            "interesting_reason": "Intertitles made complex silent-film storytelling possible.",
            "tags": ["cinema", "silent film"],
        }
        source_text = (
            "Before synchronized sound was introduced in the late 1920s, intertitles "
            "conveyed dialogue and supplied narrative information in silent films."
        )
        evidence = [
            evidence_item(
                source_text,
                host="en.wikipedia.org",
                tier="reference",
                path="wiki/Intertitle",
            ),
            evidence_item(
                source_text,
                host="silentcinemasociety.org",
                tier="other",
                path="titles",
            ),
            evidence_item(
                "An academic history examines the changing functions of intertitles in early cinema.",
                host="muse.jhu.edu",
                tier="primary",
                path="article/intertitles",
            ),
        ]

        self.assertTrue(
            quiz_evidence.evidence_mentions_answer(evidence[0], question["correct_answer"])
        )
        result = quiz_evidence.precheck_question_evidence(question, evidence)
        self.assertTrue(result["passed"], result["failure_reasons"])

    def test_mauveine_early_nineteenth_century_claim_is_rejected(self) -> None:
        question = {
            "question": "Which synthetic dye did William Henry Perkin discover in the early 19th century?",
            "correct_answer": "Mauveine",
            "explanation": "Mauveine was the synthetic dye discovered by Perkin in the early 19th century.",
            "interesting_reason": "The discovery transformed the dye industry.",
            "tags": ["chemistry", "dyes"],
        }
        evidence = [
            evidence_item(
                "Mauveine was a synthetic purple dye discovered by William Henry Perkin in 1856.",
                host="sciencemuseum.org.uk",
                tier="primary",
                path="objects-and-stories/mauveine",
            ),
            evidence_item(
                "William Henry Perkin discovered the synthetic dye mauveine in 1856.",
                host="bbc.co.uk",
                tier="reputable",
                path="history/mauveine",
            ),
        ]

        result = quiz_evidence.precheck_question_evidence(question, evidence)

        self.assertFalse(result["passed"])
        self.assertTrue(any("1856" in reason for reason in result["failure_reasons"]))

    def test_kodak_brownie_disposable_camera_claim_is_rejected(self) -> None:
        question = {
            "question": "Which camera was the first commercially available disposable camera?",
            "correct_answer": "Kodak Brownie",
            "explanation": "The Kodak Brownie was the first commercially available disposable camera.",
            "interesting_reason": "It made snapshot photography accessible to a mass audience.",
            "tags": ["photography", "cameras"],
        }
        evidence = [
            evidence_item(
                "Kodak introduced the Kodak Brownie in 1900 as an inexpensive snapshot camera.",
                host="si.edu",
                tier="primary",
                path="object/kodak-brownie",
            ),
            evidence_item(
                "The Kodak Brownie popularised low-cost photography after its 1900 launch.",
                host="bbc.co.uk",
                tier="reputable",
                path="culture/kodak-brownie",
            ),
        ]

        result = quiz_evidence.precheck_question_evidence(question, evidence)

        self.assertFalse(result["passed"])
        self.assertTrue(any("risky claim" in reason for reason in result["failure_reasons"]))

    def test_unsupported_first_artificial_gemstone_claim_is_rejected(self) -> None:
        question = {
            "question": "Which process produced the first commercially available artificial gemstones?",
            "correct_answer": "Verneuil process",
            "explanation": "The Verneuil process produced the first commercially available artificial gemstones.",
            "interesting_reason": "The method made laboratory-grown ruby production practical.",
            "tags": ["gemstones", "invention"],
        }
        evidence = [
            evidence_item(
                "The Verneuil process is a flame-fusion method used to manufacture synthetic ruby.",
                host="gia.edu",
                tier="primary",
                path="gem-research/verneuil-process",
            ),
            evidence_item(
                "Auguste Verneuil developed the Verneuil process for producing synthetic corundum.",
                host="britannica.com",
                tier="reputable",
                path="technology/verneuil-process",
            ),
        ]

        result = quiz_evidence.precheck_question_evidence(question, evidence)

        self.assertFalse(result["passed"])
        self.assertTrue(any("risky claim" in reason for reason in result["failure_reasons"]))

    def test_explicitly_sourced_first_and_year_claim_can_pass_precheck(self) -> None:
        question = {
            "question": "Which nation became the first to win five men's FIFA World Cups in 2002?",
            "correct_answer": "Brazil",
            "explanation": "Brazil became the first nation to win five men's FIFA World Cups in 2002.",
            "interesting_reason": "The fifth title extended the competition's most famous record.",
            "tags": ["football", "world cup"],
        }
        claim = "Brazil became the first nation to win five men's FIFA World Cups in 2002."
        evidence = [
            evidence_item(claim, host="fifa.com", tier="primary", path="tournaments/2002-brazil"),
            evidence_item(claim, host="bbc.co.uk", tier="reputable", path="sport/football/brazil-2002"),
        ]

        result = quiz_evidence.precheck_question_evidence(question, evidence)

        self.assertTrue(result["passed"], result["failure_reasons"])
        self.assertEqual(len(result["qualified_evidence_indices"]), 2)


if __name__ == "__main__":
    unittest.main()
