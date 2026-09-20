"""Regressions from observed production content, with no live model calls."""
import json
import sqlite3
import unittest

import daily_quiz
import daily_map_game
import server
from tools import discover_map_places as discovery
from test_daily_quiz import valid_question
import test_map_place_discovery


class QuizEditorialTests(unittest.TestCase):
    def test_entities_are_normalized_before_validating_choices(self):
        q = valid_question()
        q['choices'] = ['Johannes M&uuml;ller', 'Helmholtz', 'Weber', 'Fechner']
        q['correct_answer'] = 'Johannes M&uuml;ller'
        result = daily_quiz.validate_question(q)
        self.assertTrue(result.passed, result.reason)
        self.assertEqual(result.question['correct_answer'], 'Johannes Müller')
        self.assertEqual(q['correct_answer'], 'Johannes M&uuml;ller')

    def test_sanfrecce_name_matching_is_rejected(self):
        q = valid_question('football')
        q.update(question="Which Japanese club uses the name 'Sanfrecce', meaning three arrows?",
                 choices=['Sanfrecce Hiroshima', 'Urawa Red Diamonds', 'Kashima Antlers', 'Gamba Osaka'],
                 correct_answer='Sanfrecce Hiroshima')
        self.assertIn('gives away', daily_quiz.validate_question(q).reason)

    def test_shared_quoted_word_is_not_a_giveaway(self):
        self.assertFalse(daily_quiz.answer_is_given_away("Which 'United' club won the competition?", ['Manchester United', 'Leeds United', 'West Ham United', 'Newcastle United'], 'Leeds United'))

    def test_stadium_themes_cannot_fill_one_round(self):
        first = valid_question('football')
        first.update(question='Which stadium hosted the deciding match in this tournament?', correct_answer='Maracana')
        second = valid_question('football', 'medium')
        second.update(question="Which club plays at the stadium nicknamed the Marakana?", correct_answer='Red Star Belgrade')
        self.assertFalse(daily_quiz.check_repetition(second, [first], reject_any_repeated_answer=True).passed)
        second['subject'] = 'general_knowledge'
        self.assertTrue(daily_quiz.check_repetition(second, [first], reject_any_repeated_answer=True).passed)

    def test_completed_result_decodes_text_and_exposes_verified_payoff(self):
        q = {**valid_question(), 'id': 77, 'choices': ['M&uuml;ller', 'Weber', 'Fechner', 'Helmholtz'], 'correct_answer': 'M&uuml;ller', 'interesting_reason': 'A verified memorable payoff.'}
        before = server.quiz_content_version([q])
        answers = [{'questionId': daily_quiz.public_question_id(77), 'choiceId': daily_quiz.public_choice_id(77, 0)}]
        _, results, scores = server.adjudicate_quiz_answers([q], answers)
        self.assertEqual(results[0]['correctAnswer'], 'Müller')
        self.assertEqual(results[0]['interestingReason'], q['interesting_reason'])
        self.assertTrue(results[0]['correct'])
        self.assertEqual(before, server.quiz_content_version([q]))

    def test_failed_ideas_survive_short_feedback_window(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        daily_quiz.initialize_database(conn)
        for index in range(20):
            daily_quiz.save_attempt(conn, quiz_date='2026-09-20', subject='football', difficulty='easy', attempt_number=index+1, provider='fixture', generated={'correct_answer': f'Club {index}'}, critic=None, passed=False, failure_reason='Unsupported premise.')
        self.assertEqual(len(daily_quiz.failed_answer_blocklist(conn, '2026-09-20', 'football')), 20)


class MapEditorialTests(unittest.TestCase):
    def test_failed_place_alias_punctuation_is_blocked(self):
        for alias in ('Mont-Saint-Michel', 'Mont St. Michel', 'Mont Saint Michel'):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                discovery.reject_excluded_place([alias], ['Mont Saint-Michel'])

    def test_stadium_cannot_hide_under_engineering(self):
        fixture = test_map_place_discovery.DiscoveryTests()
        source, _, pages, proposal = fixture.source_fixture()
        pages['Target']['title'] = 'Panathenaic Stadium'
        proposal['place_type'] = 'engineering'
        with self.assertRaisesRegex(ValueError, 'stadium'):
            discovery.resolve(proposal, source, [], [])
        self.assertEqual(source.page.call_count, 1)

    def test_historical_country_claim_does_not_make_current_country_ambiguous(self):
        def claim(name, qualifiers=None):
            return {'rank':'normal','qualifiers':qualifiers or {},'mainsnak':{'snaktype':'value','datavalue':{'value':{'id':name}}}}
        entity={'claims':{'P17':[claim('Q15180', {'P582':[{}]}), claim('Q159')]}}
        self.assertEqual(discovery.claim_values(entity,'P17'), [{'id':'Q159'}])

    def test_static_material_hook_fails_shared_gate(self):
        result = daily_map_game.local_map_clue_critique({'canonical_name':'Test Stadium'}, {'hard':'It is the only stadium in the world built entirely of marble.', 'medium':'This landmark is in Athens, the capital of Greece.', 'easy':'In central Athens, look east of the Zappeion Exhibition Hall.', 'reveal':'Test Stadium'})
        self.assertTrue(any('construction material' in reason for reason in result['failure_reasons']))
