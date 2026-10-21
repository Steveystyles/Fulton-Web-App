from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import automatic_map_pool as pool
from tools import controlled_map_round as controlled
from tools import discover_map_places as discovery


class AutomaticPoolTests(unittest.TestCase):
    def test_cli_treats_completed_interest_audit_as_success(self):
        with patch('sys.argv', ['automatic_map_pool', '--source-db', 'unused.db']), \
             patch.object(pool.rewriter, 'load_env_file'), \
             patch.object(pool, 'maintain', return_value={
                 'status': 'audited', 'ready': 1, 'run_id': 'fixture', 'place': 'CN Tower'}):
            self.assertEqual(pool.main(), 0)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / 'test.db'
        self.clock = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
        clock = patch.object(pool, 'now', side_effect=lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        profile = patch.object(controlled.daily_map_game, 'map_learning_profile_hash', return_value='test-profile')
        profile.start()
        self.addCleanup(profile.stop)
        with closing(sqlite3.connect(self.database)) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            pool.initialize(conn)
            conn.commit()
        self.place = next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG) if p['id'] == 'atomium')
        self.payload = {'place_id': self.place['id'], 'selection_reason': 'A memorable scientific idea with sourced local map placement.',
                        'clues': {k: {'text': v['text'], 'fact_id': k} for k, v in self.place['facts'].items()}}
        self.result = controlled.validate_result(self.payload, [self.place])
        self.verdict = {**{k: True for k in pool.CHECKS},
                        'chronology_consistent': True, 'interesting_hook_score': 5}

    def connect(self):
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def queue(self, origin='bootstrap'):
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result, self.verdict, origin=origin)
            conn.commit()

    def alignment_report(self, *, aligned=False):
        report_root = self.root / 'reports'
        report_root.mkdir(exist_ok=True)
        path = report_root / 'saved-discovery.json'
        hard = self.result['clue_ladder']['hard']
        proposal = (hard if aligned else
                    'A helicopter hoisted giant antenna sections over the fairground in a daring night operation.')
        selected = {
            'id': self.place['id'], 'canonical_name': self.place['canonical_name'],
            'proposal_reason': proposal,
            'evidence': {'article': {'text': ('Unrelated geographical background. ' * 80) + proposal}},
        }
        hook_indexes = discovery.proposal_hook_passage_indexes(selected)
        self.assertTrue(hook_indexes)
        source_id = f'article-{max(hook_indexes)}' if aligned else 'article-0'
        if not aligned:
            self.assertNotIn(0, hook_indexes)
        report = {
            'candidate': {'id': self.place['id']},
            'result': self.result,
            'resolved_candidates': [selected],
            'model_output': {'facts': {'hard': {'text': hard, 'source_ids': [source_id]}}},
        }
        path.write_text(json.dumps(report), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute('INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,report_path) '
                         'VALUES(?,?,?,?,?,?)',
                         ('saved-run', self.clock.date().isoformat(), '2026-09-09',
                          self.clock.isoformat(), 'added', str(path)))
            conn.commit()
        return report_root

    def test_old_unused_map_hook_is_rejected_from_original_discovery_report(self):
        self.queue('discovery')
        reports = self.alignment_report()
        with closing(self.connect()) as conn:
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [self.place['canonical_name']])
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [])
            row = conn.execute('SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(row['state'], 'rejected')
            verification = json.loads(row['verification'])
            self.assertEqual(verification['hook_rejection'], 'abandoned proposed discovery hook')
            self.assertEqual(verification['proposal_alignment_audit']['status'], 'rejected')

    def test_old_aligned_map_hook_is_stamped_without_quarantining(self):
        self.queue('discovery')
        reports = self.alignment_report(aligned=True)
        with closing(self.connect()) as conn:
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [])
            row = conn.execute('SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(row['state'], 'ready')
            self.assertEqual(json.loads(row['verification'])['proposal_alignment_audit']['status'], 'passed')

    def test_map_reaudit_skips_operator_corrections_and_missing_reports(self):
        self.queue('discovery')
        reports = self.alignment_report()
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries').fetchone()[0])
            verification['operator_correction'] = {'reason': 'Reviewed by editor'}
            conn.execute('UPDATE automatic_map_entries SET verification=?', (json.dumps(verification),))
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [])
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')
            del verification['operator_correction']
            conn.execute('UPDATE automatic_map_entries SET verification=?', (json.dumps(verification),))
            conn.execute("UPDATE automatic_map_runs SET report_path='outside-root.json'")
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [])
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')

    def test_map_reaudit_never_changes_a_used_round(self):
        self.queue('discovery')
        reports = self.alignment_report()
        with closing(self.connect()) as conn:
            conn.execute("UPDATE automatic_map_entries SET state='used',used_date='2026-09-08'")
            self.assertEqual(pool.quarantine_unaligned_ready(conn, reports), [])
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'used')

    def test_rejected_factual_round_teaches_all_three_clues_not_just_its_hook(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries').fetchone()[0])
            verification.update(editorial_rejection=True,
                                hook_rejection='unsupported factual claims',
                                ready_audit={'evidence_supported': False,
                                             'chronology_consistent': True,
                                             'reason': 'The easy clue invents a nearby feature.'})
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=?",
                         (json.dumps(verification),))
            lessons = pool.rejected_interest_lessons(conn)
            self.assertEqual(len(lessons), 1)
            self.assertIn('unsupported factual claims', lessons[0]['failure_reason'])
            self.assertEqual(lessons[0]['attempted_clues'], {
                level: self.result['clue_ladder'][level] for level in ('hard', 'medium', 'easy')})

    def test_rejected_lessons_keep_distinct_failure_types_in_small_prompt(self):
        with closing(self.connect()) as conn:
            for index, kind in enumerate(('unsupported', 'hook', 'hook', 'hook')):
                candidate = {**self.place, 'id': f'place-{index}',
                             'canonical_name': f'Place {index}'}
                verification = {'editorial_rejection': True, 'interesting_hook_score': 5,
                                'ready_audit': {'evidence_supported': kind != 'unsupported',
                                                'chronology_consistent': True,
                                                'reason': kind}}
                if kind == 'hook':
                    verification['hook_rejection'] = 'abandoned proposed discovery hook'
                conn.execute(
                    'INSERT INTO automatic_map_entries(id,state,candidate,result,verification,created_at,expires_at,origin) '
                    'VALUES(?,?,?,?,?,?,?,?)',
                    (candidate['id'], 'rejected', json.dumps(candidate), json.dumps(self.result),
                     json.dumps(verification), (self.clock + timedelta(minutes=index)).isoformat(),
                     (self.clock + timedelta(days=14)).isoformat(), 'discovery'))
            lessons = pool.rejected_interest_lessons(conn, limit=3)
            self.assertEqual(len(lessons), 3)
            self.assertEqual(lessons[0]['place'], 'Place 3')
            self.assertEqual(lessons[1]['place'], 'Place 0')
            self.assertIn('unsupported factual claims', lessons[1]['failure_reason'])

    def test_replacing_a_rejected_place_preserves_hook_memory_and_feedback(self):
        self.queue('discovery')
        alternative = deepcopy(self.result)
        alternative['clue_ladder']['hard'] = 'A different, verified story about this same place.'
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries').fetchone()[0])
            verification.update(editorial_rejection=True,
                                hook_rejection='abandoned proposed discovery hook')
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=?",
                         (json.dumps(verification),))
            with patch.object(controlled, 'validate_result', return_value=alternative):
                pool.add(conn, self.place, alternative, self.verdict, origin='discovery')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_rejected_hooks').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')
            lessons = pool.rejected_interest_lessons(conn)
            self.assertEqual(lessons[0]['attempted_clues']['hard'], self.result['clue_ladder']['hard'])
            conn.execute("UPDATE automatic_map_entries SET state='expired'")
            with self.assertRaisesRegex(ValueError, 'previously rejected Map hook'):
                pool.add(conn, self.place, self.result, self.verdict, origin='discovery')

    def test_next_date_skips_offdays_and_already_published_games(self):
        with closing(self.connect()) as conn:
            self.assertEqual(pool.next_date(conn), '2026-09-09')
            conn.execute("INSERT INTO daily_map_puzzles(puzzle_date,status) VALUES(?,?)",
                         ('2026-09-09', 'published'))
            self.assertEqual(pool.next_date(conn), '2026-09-12')

    def test_budget_is_by_actual_day_not_future_game_date_and_survives_restart(self):
        for index in range(8):
            budget = pool.Budget(self.database, f'2026-10-{index+1:02d}')
            self.assertEqual(budget.attempt_number, index + 1)
            for _ in range(discovery.MAX_MODEL_REQUESTS):
                budget.spend('model')
            with self.assertRaisesRegex(ValueError, 'per-attempt request limit'):
                budget.spend('model')
            budget.complete('failed', {})
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT day,attempts,model_requests FROM automatic_map_usage').fetchone()
            self.assertEqual(tuple(row), ('2026-09-08', 8, 8 * discovery.MAX_MODEL_REQUESTS))
        self.clock += timedelta(days=1)
        next_day = pool.Budget(self.database, '2026-12-01')
        self.assertEqual(next_day.budget_day, '2026-09-09')
        self.assertEqual(next_day.attempt_number, 1)

    def test_live_lease_prevents_parallel_replenishment_and_expired_lease_keeps_usage(self):
        first = pool.Budget(self.database, '2026-09-08')
        first.spend('model')
        with self.assertRaisesRegex(ValueError, 'lease'):
            pool.Budget(self.database, '2026-09-09')
        self.clock += timedelta(minutes=16)
        pool.Budget(self.database, '2026-09-09')
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT status FROM automatic_map_runs WHERE id=?', (first.id,)).fetchone()[0], 'abandoned')
            self.assertEqual(conn.execute('SELECT model_requests FROM automatic_map_usage').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            first.spend('model')

    def test_source_request_cap_rolls_back_partial_attempt_increment(self):
        budget = pool.Budget(self.database, '2026-09-08')
        for _ in range(discovery.MAX_SOURCE_REQUESTS):
            budget.spend('source')
        with self.assertRaises(ValueError):
            budget.spend('source')
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT source_requests FROM automatic_map_usage').fetchone()[0],
                             discovery.MAX_SOURCE_REQUESTS)

    def test_publication_and_queue_consumption_are_atomic_and_preserve_caller_work(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            conn.execute('CREATE TABLE caller_work(value TEXT)')
            conn.execute("INSERT INTO caller_work VALUES('keep')")
            original = controlled.publish_validated_round
            def fail(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError('failure after actual publication')
            with patch.object(controlled, 'publish_validated_round', side_effect=fail), self.assertRaises(RuntimeError):
                pool.publish(conn, puzzle_date='2026-09-08')
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM daily_map_puzzles').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT value FROM caller_work').fetchone()[0], 'keep')
            result = pool.publish(conn, puzzle_date='2026-09-08')
            self.assertEqual(result['status'], 'published')
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'used')
            conn.commit()
            prior = conn.execute('SELECT COUNT(*) FROM map_place_pool').fetchone()[0]
            self.assertEqual(pool.publish(conn, puzzle_date='2026-09-08')['status'], 'published')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM map_place_pool').fetchone()[0], prior)
            with self.assertRaises(ValueError):
                pool.publish(conn, puzzle_date='2026-09-09')

    def test_expired_and_tampered_rounds_cannot_publish(self):
        self.queue()
        self.clock += timedelta(days=pool.MAX_AGE_DAYS + 1)
        with closing(self.connect()) as conn, self.assertRaisesRegex(ValueError, 'No eligible'):
            pool.publish(conn, puzzle_date='2026-10-14')
        self.clock -= timedelta(days=pool.MAX_AGE_DAYS + 1)
        with closing(self.connect()) as conn:
            changed = deepcopy(self.result)
            changed['clue_ladder']['hard'] = 'A changed clue that has not been through the verification step.'
            conn.execute('UPDATE automatic_map_entries SET result=?', (json.dumps(changed),))
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'checked payload'):
                pool.publish(conn, puzzle_date='2026-09-08')

    def test_legacy_ready_round_must_pass_interest_audit_before_publication(self):
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result,
                     {k: True for k in pool.CHECKS}, origin='discovery')
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'No eligible'):
                pool.publish(conn, puzzle_date='2026-09-08')
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {
            'interesting_hook_score': 5, 'evidence_supported': True,
            'chronology_consistent': True, 'reason': 'A striking scientific idea.',
        }
        outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'audited')
        self.assertEqual(outcome['ready'], 1)
        self.assertEqual(provider.call_with_fallback.call_args.kwargs['model_attr'], 'critic_model')
        self.assertIn('past_editorial_corrections',
                      provider.call_with_fallback.call_args.kwargs['prompt'])
        with closing(self.connect()) as conn:
            self.assertEqual(pool.publish(conn, puzzle_date='2026-09-08')['status'], 'published')

    def test_previous_interest_audit_is_rechecked_under_new_editorial_standard(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute(
                'SELECT verification FROM automatic_map_entries').fetchone()[0])
            verification['ready_audit'] = {
                'version': pool.READY_AUDIT_VERSION - 1,
                'interesting_hook_score': 5,
                'evidence_supported': True,
                'chronology_consistent': True,
                'reason': 'The old critic approved this round.',
            }
            conn.execute('UPDATE automatic_map_entries SET verification=?',
                         (json.dumps(verification),))
            conn.commit()
            self.assertEqual(pool.eligible(conn, '2026-09-09'), [])
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {
            'interesting_hook_score': 2, 'evidence_supported': True,
            'chronology_consistent': True,
            'reason': 'Factual, but not an enjoyable place-discovery hook.',
        }
        outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'audited')
        self.assertEqual(outcome['ready'], 0)
        with closing(self.connect()) as conn:
            state, verification_text = conn.execute(
                'SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(state, 'rejected')
            self.assertEqual(json.loads(verification_text)['ready_audit']['version'],
                             pool.READY_AUDIT_VERSION)

    def test_legacy_weak_round_is_rejected_and_cannot_reenter_queue(self):
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result,
                     {k: True for k in pool.CHECKS}, origin='discovery')
            conn.commit()
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {
            'interesting_hook_score': 2, 'evidence_supported': True,
            'chronology_consistent': True, 'reason': 'Only an ordinary design detail.',
        }
        outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'audited')
        self.assertEqual(outcome['ready'], 0)
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(row[0], 'rejected')
            self.assertTrue(json.loads(row[1])['editorial_rejection'])
            lessons = pool.rejected_interest_lessons(conn)
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0]['attempted_clues']['hard'], self.result['clue_ladder']['hard'])
            self.assertIn('2/5', lessons[0]['failure_reason'])
            with self.assertRaisesRegex(ValueError, 'Editorially rejected'):
                pool.add(conn, self.place, self.result, self.verdict, origin='discovery')
        failed = {'status': 'failed', 'error': 'No source.', 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                          provider_factory=Mock(return_value=Mock(requests=[])))
        passed_lessons = discover.call_args.kwargs['failure_lessons']
        self.assertIn(self.result['clue_ladder']['hard'],
                      [item['attempted_clues']['hard'] for item in passed_lessons])

    def queue_two_legacy_rounds(self):
        second = next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG)
                      if p['id'] == 'sydney-opera-house')
        payload = {'place_id': second['id'], 'selection_reason': 'A memorable sourced landmark.',
                   'clues': {k: {'text': v['text'], 'fact_id': k} for k, v in second['facts'].items()}}
        second_result = controlled.validate_result(payload, [second])
        with closing(self.connect()) as conn:
            for candidate, result in ((self.place, self.result), (second, second_result)):
                pool.add(conn, candidate, result, {k: True for k in pool.CHECKS}, origin='discovery')
            conn.commit()
        return second

    def test_legacy_interest_backlog_is_audited_in_one_bounded_request(self):
        second = self.queue_two_legacy_rounds()
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {'audits': [
            {'id': second['id'], 'interesting_hook_score': 2, 'evidence_supported': True,
             'chronology_consistent': True, 'reason': 'Only a design detail.'},
            {'id': self.place['id'], 'interesting_hook_score': 5, 'evidence_supported': True,
             'chronology_consistent': True, 'reason': 'Memorable discovery.'},
        ]}
        outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'audited')
        self.assertEqual(outcome['ready'], 1)
        self.assertEqual(len(outcome['places']), 2)
        provider.call_with_fallback.assert_called_once()
        self.assertEqual(provider.call_with_fallback.call_args.kwargs['model_attr'], 'critic_model')
        self.assertEqual(provider.call_with_fallback.call_args.kwargs['schema']['properties']['audits']['maxItems'], 2)
        with closing(self.connect()) as conn:
            rows = {row[0]: (row[1], json.loads(row[2])) for row in conn.execute(
                'SELECT id,state,verification FROM automatic_map_entries')}
            self.assertEqual(rows[self.place['id']][0], 'ready')
            self.assertEqual(rows[second['id']][0], 'rejected')
            self.assertTrue(rows[second['id']][1]['editorial_rejection'])
            self.assertEqual(conn.execute('SELECT attempts FROM automatic_map_usage').fetchone()[0], 1)

    def test_full_legacy_queue_still_audits_and_rejects_unsupported_history(self):
        second = self.queue_two_legacy_rounds()
        with patch.object(pool, 'TARGET_READY', 1):
            provider = Mock(requests=[])
            provider.call_with_fallback.return_value = {'audits': [
                {'id': self.place['id'], 'interesting_hook_score': 5,
                 'evidence_supported': False, 'chronology_consistent': False,
                 'reason': 'The cited passage concerns a different century.'},
                {'id': second['id'], 'interesting_hook_score': 5,
                 'evidence_supported': True, 'chronology_consistent': True,
                 'reason': 'Supported and memorable.'},
            ]}
            outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                    provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'audited')
        self.assertEqual(outcome['ready'], 1)
        provider.call_with_fallback.assert_called_once()
        self.assertIn('different periods', provider.call_with_fallback.call_args.kwargs['prompt'])
        with closing(self.connect()) as conn:
            rejected = json.loads(conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id='atomium'"
            ).fetchone()[0])
            self.assertFalse(rejected['ready_audit']['evidence_supported'])
            self.assertFalse(rejected['ready_audit']['chronology_consistent'])
            self.assertEqual(conn.execute(
                "SELECT state FROM automatic_map_entries WHERE id='atomium'"
            ).fetchone()[0], 'rejected')
            lessons = pool.rejected_interest_lessons(conn)
            self.assertEqual(len(lessons), 1)
            self.assertIn('unsupported factual claims', lessons[0]['failure_reason'])

    def test_malformed_ready_audit_cannot_approve_a_round(self):
        self.queue()
        for bad in ({'interesting_hook_score': 5, 'evidence_supported': True,
                     'reason': 'Missing chronology.'},
                    {'interesting_hook_score': 5, 'evidence_supported': 'true',
                     'chronology_consistent': True, 'reason': 'String is not a verdict.'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pool.parse_ready_audit(bad)

    def test_consequential_historical_label_needs_explicit_passage_support(self):
        candidate = deepcopy(self.place)
        candidate['facts']['hard']['supporting_quotes'] = [
            'Hundreds of residents were held hostage inside the building by soldiers.'
        ]
        result = deepcopy(self.result)
        result['clue_ladder']['hard'] = (
            'During the battle this building became a concentration camp where residents were held hostage.'
        )
        self.assertEqual(pool.unsupported_critical_labels(candidate, result), ['concentration camp'])
        with closing(self.connect()) as conn, \
                patch.object(controlled, 'validate_result', return_value=result), \
                self.assertRaisesRegex(ValueError, 'light Map game'):
            pool.add(conn, candidate, result, self.verdict, origin='discovery')
        candidate['facts']['hard']['supporting_quotes'] = [
            'During the battle the building became a concentration camp where residents were held hostage.'
        ]
        self.assertEqual(pool.unsupported_critical_labels(candidate, result), [])

    def test_light_game_tone_rejects_victim_hooks_but_keeps_history(self):
        examples = (
            ('This church was used as a concentration camp.', 'camp confinement'),
            ('Hundreds of residents were held hostage inside this church.', 'hostage-taking'),
            ('Young cadets died defending this hilltop stronghold.', 'victim deaths'),
            ('Defenders jammed the elevator with a matchbox and considered deploying an '
             'asphyxiating fire-fighting system to deter Soviet troops.',
             'threatened serious harm'),
            ('Defenders jammed the elevator with a matchbox, forcing Soviet troops to climb '
             'a thousand steps while threatening an oxygen-removing fire-fighting system.',
             'threatened serious harm'),
            ('The fortress served as a military prison to incarcerate members of Native American tribes.',
             'victim confinement'),
            ('A leader was seized under a white flag of truce here.', 'betrayal and detention'),
            ('Apparently, a stonemason from the rival order supervised this castle.',
             'hedged historical claim'),
            ("Apparently during a truce with the Teutonic Order, the construction works "
             "of this island fortress were supervised by the Order's stonemason.",
             'hedged historical claim'),
            ('Reflective skyscrapers disrupted broadcast signals, prompting construction '
             'of this tower for higher antennas.', 'routine signal-engineering premise'),
            ('As downtown skyscrapers multiplied, their reflective surfaces disrupted '
             'broadcast signals, prompting the construction of this soaring tower to mount '
             'higher antennas and restore line-of-sight communication links.',
             'routine signal-engineering premise'),
            ('At the beginning of the Axis occupation in 1941, German soldiers raised '
             'the Nazi war flag here, which was later taken down in an act of resistance.',
             'wartime occupation'),
            ('After an empire fell, this site continued to be inhabited with regular pond '
             'maintenance.', 'routine upkeep'),
            ('It served as the main venue for the newly elected Constituent Assembly.',
             'routine institutional history'),
            ('Its sloping roof turns an opera house into a public square.', None),
            ('A captain had thirty men run across the deck, and the ship rolled alarmingly.', None),
            ('A Persian emperor plundered this fort and seized its famous throne.', None),
            ('An eruption buried this Roman city and preserved its streets.', None),
        )
        for clue, expected in examples:
            with self.subTest(clue=clue):
                self.assertEqual(pool.unsuitable_game_hook({'clue_ladder': {'hard': clue}}), expected)
        self.assertEqual(pool.rejected_hook_reason({'tone_rejection': 'hostage-taking'}),
                         'hostage-taking')
        self.assertIn('specific player payoff', pool.READY_AUDIT_INSTRUCTIONS)
        self.assertIn('Factual support', pool.READY_AUDIT_INSTRUCTIONS)

    def test_maintenance_quarantines_old_victim_hook_without_model_request(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            result = json.loads(conn.execute('SELECT result FROM automatic_map_entries').fetchone()[0])
            result['clue_ladder']['hard'] = 'Hundreds of residents were held hostage inside this building.'
            conn.execute('UPDATE automatic_map_entries SET result=?', (json.dumps(result),))
            conn.commit()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': ''}):
            outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None)
        self.assertEqual(outcome['status'], 'deferred')
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(row[0], 'rejected')
            verification = json.loads(row[1])
            self.assertEqual(verification['hook_rejection'], 'hostage-taking')
            self.assertTrue(verification['editorial_rejection'])
            self.assertIn('Unsuitable Map hook', pool.rejected_interest_lessons(conn)[0]['failure_reason'])
            # Reject the hook, not the place: a genuinely different, suitable
            # story may return to the ordinary selection pool.
            pool.add(conn, self.place, self.result, self.verdict, origin='discovery')
            conn.commit()
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')

    def test_ready_audit_cannot_override_missing_critical_label_evidence(self):
        self.queue_two_legacy_rounds()
        with closing(self.connect()) as conn:
            candidate, result, verification = conn.execute(
                "SELECT candidate,result,verification FROM automatic_map_entries WHERE id='atomium'"
            ).fetchone()
            candidate, result = json.loads(candidate), json.loads(result)
            verification = json.loads(verification)
            candidate['facts']['hard']['supporting_quotes'] = ['Residents were held hostage in the building.']
            result['clue_ladder']['hard'] = 'This building was used as a concentration camp.'
            verification['ready_audit'] = {
                'version': pool.READY_AUDIT_VERSION, 'interesting_hook_score': 5,
                'evidence_supported': True, 'chronology_consistent': True,
                'reason': 'The previous model incorrectly approved this.',
            }
            conn.execute("UPDATE automatic_map_entries SET candidate=?,result=?,verification=? WHERE id='atomium'",
                         (json.dumps(candidate), json.dumps(result), json.dumps(verification)))
            conn.commit()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': ''}):
            outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None)
        self.assertEqual(outcome['status'], 'deferred')
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT state,verification FROM automatic_map_entries WHERE id='atomium'").fetchone()
            self.assertEqual(row[0], 'rejected')
            verification = json.loads(row[1])
            self.assertTrue(verification['ready_audit']['evidence_supported'])
            self.assertEqual(verification['hook_rejection'], 'camp confinement')

    def test_malformed_interest_batch_does_not_partially_update_queue(self):
        self.queue_two_legacy_rounds()
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {'audits': [
            {'id': self.place['id'], 'interesting_hook_score': 5, 'reason': 'Good.'},
            {'id': self.place['id'], 'interesting_hook_score': 2, 'reason': 'Duplicate.'},
        ]}
        outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                provider_factory=lambda _budget: provider)
        self.assertEqual(outcome['status'], 'failed')
        with closing(self.connect()) as conn:
            for state, verification in conn.execute('SELECT state,verification FROM automatic_map_entries'):
                self.assertEqual(state, 'ready')
                self.assertNotIn('interesting_hook_score', json.loads(verification))

    def test_published_round_keeps_saved_clues_and_hides_answer_at_each_stage(self):
        self.queue()
        with closing(self.connect()) as conn:
            pool.publish(conn, puzzle_date='2026-09-08')
            conn.commit()
            row = dict(controlled.daily_map_game.level_rows(conn, '2026-09-08', -1)[0])
            for count in range(3):
                row['progress_revealed_hint_count'] = count
                player = controlled.daily_map_game.serialize_level(row)
                self.assertEqual(len(player['clues']), count+1)
                self.assertEqual(len(player['mapAnchors']), count)
                self.assertNotIn('result', player)
            place = conn.execute("SELECT scoring_radius_m,clue_generation_source FROM map_place_pool WHERE slug LIKE 'controlled-%'").fetchone()
            self.assertEqual(tuple(place), (10000, 'automatic-map-bootstrap'))

    def report(self):
        place = deepcopy(self.place)
        place['retrieved_on'] = discovery.date.today().isoformat()
        place['sources']['article'] = next(iter(place['sources'].values()))
        place['evidence'] = {'article': {'text': ' '.join(f['text'] for f in place['facts'].values())}}
        ids = [p['id'] for p in discovery.evidence_units(place)]
        output = {'place_id': place['id'], 'selection_reason': self.payload['selection_reason'],
                  'facts': {k: {'text': f['text'], 'source_ids': ids} for k, f in place['facts'].items()}}
        candidate, result = discovery.validate_selection(output, [place])
        return {'status': 'needs_source_review', 'candidate': candidate, 'result': result,
                'model_output': output, 'resolved_candidates': [place], 'rejections': []}

    def test_independent_verifier_can_read_official_hard_hook(self):
        place = deepcopy(self.place)
        hard = place['facts']['hard']['text']
        place['retrieved_on'] = discovery.date.today().isoformat()
        place['sources']['article'] = next(iter(place['sources'].values()))
        place['sources']['unesco'] = 'https://whc.unesco.org/en/list/252/'
        place['evidence'] = {
            'article': {'text': ' '.join(place['facts'][level]['text'] for level in ('medium', 'easy'))},
            'official': {'text': hard, 'hook_passage': hard},
        }
        place['proposal_reason'] = hard
        output = {'place_id': place['id'], 'selection_reason': self.payload['selection_reason'],
                  'facts': {'hard': {'text': hard, 'source_ids': ['official-hook']},
                            'medium': {'text': place['facts']['medium']['text'],
                                       'quote': place['facts']['medium']['text']},
                            'easy': {'text': place['facts']['easy']['text'],
                                     'quote': place['facts']['easy']['text']}}}
        candidate, result = discovery.validate_selection(output, [place])
        report = {'candidate': candidate, 'result': result, 'model_output': output,
                  'resolved_candidates': [place]}
        verdict = {**self.verdict,
                   'levels': {level: {'supported': True,
                                     'source_ids': ['official-hook' if level == 'hard' else 'article-0']}
                              for level in controlled.LEVELS},
                   'reason': 'The official passage supports the design story.'}
        provider = Mock()
        provider.call_with_fallback.return_value = verdict
        self.assertEqual(pool.verify(report, provider), verdict)
        self.assertIn('official-hook', provider.call_with_fallback.call_args.kwargs['prompt'])

    def test_independent_verifier_rejects_unsupported_or_fabricated_citations(self):
        report = self.report()
        ids = [p['id'] for p in discovery.evidence_units(report['resolved_candidates'][0])]
        verdict = {**self.verdict, 'levels': {k: {'supported': True, 'source_ids': ids} for k in controlled.LEVELS}, 'reason': 'Supported by supplied passages.'}
        provider = Mock()
        provider.call_with_fallback.return_value = verdict
        self.assertEqual(pool.verify(report, provider), verdict)
        self.assertEqual(provider.call_with_fallback.call_args.kwargs['model_attr'], 'critic_model')
        prompt = provider.call_with_fallback.call_args.kwargs['prompt']
        self.assertIn('obscure procurement detail', prompt)
        self.assertIn('absence of an event', prompt)
        self.assertIn('editorial discovery hook', prompt)
        self.assertIn('chronology_consistent=false', prompt)
        self.assertIn('chronology_consistent', provider.call_with_fallback.call_args.kwargs['schema']['required'])
        for change in ('unsupported', 'citation', 'uncertain', 'chronology'):
            altered = deepcopy(verdict)
            if change == 'unsupported': altered['levels']['hard']['supported'] = False
            if change == 'citation': altered['levels']['hard']['source_ids'] = ['invented']
            if change == 'uncertain': altered['identity_correct'] = 'true'
            if change == 'chronology': altered['chronology_consistent'] = False
            provider.call_with_fallback.return_value = altered
            with self.subTest(change=change), self.assertRaises(ValueError):
                pool.verify(report, provider)

    def test_publication_requires_legacy_reaudit_and_rejects_failed_chronology(self):
        legacy = {key: True for key in pool.CHECKS}
        legacy['interesting_hook_score'] = 5
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result, legacy, origin='discovery')
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'No eligible'):
                pool.publish(conn, puzzle_date='2026-09-09')
        provider = Mock(requests=[])
        provider.call_with_fallback.return_value = {
            'interesting_hook_score': 5, 'evidence_supported': True,
            'chronology_consistent': True, 'reason': 'Supported.',
        }
        self.assertEqual(pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                       provider_factory=lambda _budget: provider)['status'], 'audited')
        with closing(self.connect()) as conn:
            self.assertEqual(pool.publish(conn, puzzle_date='2026-09-09')['status'], 'published')

        with closing(self.connect()) as conn:
            conn.execute("DELETE FROM daily_map_puzzles WHERE puzzle_date='2026-09-09'")
            conn.execute("UPDATE automatic_map_entries SET state='ready', used_date=NULL")
            failed = json.loads(conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id=?", (self.place['id'],)
            ).fetchone()[0])
            failed['ready_audit']['chronology_consistent'] = False
            conn.execute("UPDATE automatic_map_entries SET verification=?",
                         (json.dumps(failed),))
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'No eligible'):
                pool.publish(conn, puzzle_date='2026-09-09')

    def test_unsafe_old_editorial_replacement_is_negative_feedback_only(self):
        unsafe = pool.editorial_example(
            'A historic church', 'A misleading wartime premise.',
            'Residents were held hostage inside this church.',
            'The old clue overstated the venue’s historical role.')
        self.assertEqual(unsafe['rejected_hook'], 'A misleading wartime premise.')
        self.assertNotIn('replacement_hook', unsafe)
        self.assertTrue(unsafe['negative_only'])
        self.assertIn('do not imitate it', unsafe['reason'])
        safe = pool.editorial_example(
            'A public hall', 'A generic building detail.',
            'A major public performance drew thousands here.', 'Make the story distinctive.')
        self.assertEqual(safe['replacement_hook'],
                         'A major public performance drew thousands here.')
        self.assertNotIn('negative_only', safe)

    def test_published_editorial_replacement_teaches_automatic_queue(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            pool.publish(conn, puzzle_date='2026-09-08')
            conn.execute(
                "UPDATE map_place_pool SET clue_text=?,clue_generation_source='admin-edit' "
                "WHERE id=(SELECT place_id FROM daily_map_levels LIMIT 1)",
                ('A much more memorable, place-defining scientific story.',),
            )
            conn.commit()
            feedback = pool.editorial_corrections(conn)
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]['rejected_hook'], self.result['clue_ladder']['hard'])
        self.assertIn('memorable', feedback[0]['replacement_hook'])

        report = self.report()
        provider = Mock()
        with self.assertRaisesRegex(ValueError, 'editor rejected'):
            pool.verify(report, provider, editorial_feedback=feedback)
        provider.call_with_fallback.assert_not_called()

        changed = deepcopy(report)
        changed['model_output'] = deepcopy(report['model_output'])
        changed['model_output']['facts']['hard']['text'] = 'A different supported and memorable hard hook.'
        # A new candidate is allowed through the model, which sees both sides of the correction.
        with patch.object(discovery, 'validate_selection', return_value=(
            report['candidate'], {'clue_ladder': {**report['result']['clue_ladder'],
                                                'hard': 'A different supported and memorable hard hook.'}}
        )):
            ids = [p['id'] for p in discovery.evidence_units(report['resolved_candidates'][0])]
            provider.call_with_fallback.return_value = {
                **self.verdict,
                'levels': {k: {'supported': True, 'source_ids': ids} for k in controlled.LEVELS},
                'reason': 'A strong place-defining hook.',
            }
            pool.verify(changed, provider, editorial_feedback=feedback)
        prompt = provider.call_with_fallback.call_args.kwargs['prompt']
        self.assertIn(feedback[0]['rejected_hook'], prompt)
        self.assertIn(feedback[0]['replacement_hook'], prompt)
        provider.call_with_fallback.return_value['interesting_hook_score'] = 2
        with patch.object(discovery, 'validate_selection', return_value=(
            report['candidate'], {'clue_ladder': {**report['result']['clue_ladder'],
                                                'hard': 'A different supported and memorable hard hook.'}}
        )), self.assertRaisesRegex(ValueError, 'insufficiently interesting'):
            pool.verify(changed, provider, editorial_feedback=feedback)

    def test_empty_pool_replenishes_without_any_static_catalogue_or_human_promotion(self):
        report = self.report()
        factory = Mock(return_value=Mock(requests=[]))
        with patch.object(discovery, 'discover', return_value=report) as discover, patch.object(pool, 'verify', return_value=self.verdict):
            result = pool.maintain(self.database, self.root/'reports', seed_catalog=None, provider_factory=factory)
        self.assertEqual(result['status'], 'added')
        self.assertIsNone(discover.call_args.kwargs['catalog'])
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT candidate,origin FROM automatic_map_entries').fetchone()
            self.assertEqual(json.loads(row[0])['review_status'], 'machine_checked')
            self.assertEqual(row[1], 'discovery')
            self.assertEqual(pool.publish(conn, puzzle_date='2026-09-08')['status'], 'published')

    def test_story_first_pipeline_can_be_selected_without_changing_default(self):
        report = self.report()
        factory = Mock(return_value=Mock(requests=[]))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report) as story_discover, \
             patch.object(discovery, 'discover') as legacy_discover, \
             patch.object(pool, 'verify', return_value=self.verdict):
            result = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                   provider_factory=factory)
        self.assertEqual(result['status'], 'added')
        story_discover.assert_called_once()
        legacy_discover.assert_not_called()

    def test_full_legacy_queue_does_not_block_first_story_round(self):
        report = {**self.report(), 'pipeline': 'story_first'}
        report['candidate_sha256'] = discovery.digest(report['candidate'])
        old_row = ('old', '{}', '{}', json.dumps({'source_pipeline': 'legacy'}), 'discovery')
        factory = Mock(return_value=Mock(requests=[]))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool, 'eligible', return_value=[old_row] * pool.TARGET_READY), \
             patch.object(pool, 'recoverable_report') as legacy_recovery, \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report) as discover, \
             patch.object(pool, 'verify', return_value=self.verdict):
            result = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                   provider_factory=factory)
        self.assertEqual(result['status'], 'added')
        discover.assert_called_once()
        legacy_recovery.assert_not_called()

    def test_stocking_waits_for_full_story_buffer_even_when_legacy_queue_is_full(self):
        old_row = ('old', '{}', '{}', json.dumps({'source_pipeline': 'legacy'}), 'discovery')
        story_row = ('new', '{}', '{}', json.dumps({'source_pipeline': 'story_first'}), 'discovery')
        self.assertFalse(pool.story_first_ready([story_row] + [old_row] * pool.TARGET_READY))
        self.assertTrue(pool.story_first_ready([story_row] * pool.TARGET_READY))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool, 'maintain', side_effect=[
                 {'status': 'added', 'ready': pool.TARGET_READY},
                 {'status': 'audited', 'ready': pool.TARGET_READY + 1},
                 {'status': 'audited', 'ready': pool.TARGET_READY * 2}]) as maintain, \
             patch.object(pool, 'eligible', side_effect=[
                 [old_row] * pool.TARGET_READY,
                 [story_row] + [old_row] * pool.TARGET_READY,
                 [story_row] * pool.TARGET_READY + [old_row] * pool.TARGET_READY]):
            result = pool.maintain_until_stocked(
                self.database, self.root/'reports', max_attempts=3)
        self.assertEqual(result['status'], 'stocked')
        self.assertEqual(result['attempted'], 3)
        self.assertEqual(maintain.call_count, 3)

    def test_story_round_is_preferred_to_older_legacy_fallback(self):
        places = controlled.load_catalog(controlled.DEFAULT_CATALOG)
        second = next(place for place in places if place['id'] != self.place['id'])
        second_payload = {
            'place_id': second['id'], 'selection_reason': 'A source-reviewed place with progressive map clues.',
            'clues': {key: {'text': value['text'], 'fact_id': key}
                      for key, value in second['facts'].items()},
        }
        second_result = controlled.validate_result(second_payload, [second])
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result, self.verdict, origin='discovery')
            pool.add(conn, second, second_result,
                     {**self.verdict, 'source_pipeline': 'story_first'}, origin='discovery')
            conn.commit()
            with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}):
                ranked = pool.eligible(conn, '2026-09-08')
            self.assertEqual(ranked[0][0], second['id'])
            with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'legacy'}):
                ranked = pool.eligible(conn, '2026-09-08')
            self.assertEqual(ranked[0][0], self.place['id'])

    def test_stronger_hook_beats_older_story_first_round(self):
        places = controlled.load_catalog(controlled.DEFAULT_CATALOG)
        second = next(place for place in places if place['id'] != self.place['id'])
        second_payload = {
            'place_id': second['id'], 'selection_reason': 'A sourced landmark with progressive map clues.',
            'clues': {key: {'text': value['text'], 'fact_id': key}
                      for key, value in second['facts'].items()},
        }
        second_result = controlled.validate_result(second_payload, [second])
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result,
                     {**self.verdict, 'interesting_hook_score': 4,
                      'source_pipeline': 'story_first'}, origin='discovery')
            pool.add(conn, second, second_result,
                     {**self.verdict, 'interesting_hook_score': 5}, origin='discovery')
            conn.commit()
            with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}):
                ranked = pool.eligible(conn, '2026-09-08')
            self.assertEqual(ranked[0][0], second['id'])
            self.assertEqual(ranked[1][0], self.place['id'])

    def test_story_first_report_must_match_checked_candidate_before_queueing(self):
        report = {**self.report(), 'pipeline': 'story_first',
                  'candidate_sha256': 'incorrect-digest'}
        factory = Mock(return_value=Mock(requests=[]))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report), \
             patch.object(pool, 'verify', return_value=self.verdict):
            outcome = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                    provider_factory=factory)
        self.assertEqual(outcome['status'], 'failed')
        self.assertIn('Story-first candidate changed', outcome['reason'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_entries').fetchone()[0], 0)

    def test_story_first_round_requires_separate_ready_audit_before_publication(self):
        report = {**self.report(), 'pipeline': 'story_first'}
        report['candidate_sha256'] = discovery.digest(report['candidate'])
        factory = Mock(return_value=Mock(requests=[]))
        prematurely_passed = {**self.verdict, 'ready_audit': {
            'version': pool.READY_AUDIT_VERSION, 'interesting_hook_score': 5,
            'evidence_supported': True, 'chronology_consistent': True}}
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report), \
             patch.object(pool, 'verify', return_value=prematurely_passed):
            first = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                  provider_factory=factory)
        self.assertEqual(first['status'], 'added')
        self.assertTrue(first['pending_audit'])
        self.assertEqual(first['ready'], 0)
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries').fetchone()[0])
            self.assertNotIn('ready_audit', verification)
            with self.assertRaisesRegex(ValueError, 'No eligible'):
                pool.publish(conn, puzzle_date='2026-09-08')
        audit = {'version': pool.READY_AUDIT_VERSION, 'interesting_hook_score': 5,
                 'evidence_supported': True, 'chronology_consistent': True,
                 'reason': 'Independent completed-round audit passed.'}
        with patch.object(pool, 'audit_ready_interest', return_value=audit):
            second = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                   provider_factory=factory)
        self.assertEqual(second['status'], 'audited')
        self.assertEqual(second['ready'], 1)
        with closing(self.connect()) as conn:
            published = pool.publish(conn, puzzle_date='2026-09-08')
            self.assertEqual(published['status'], 'published')
            self.assertEqual(conn.execute(
                "SELECT state FROM automatic_map_entries WHERE id=?", (self.place['id'],)
            ).fetchone()[0], 'used')

    def test_story_first_audit_rejection_feeds_next_attempt(self):
        report = {**self.report(), 'pipeline': 'story_first'}
        report['candidate_sha256'] = discovery.digest(report['candidate'])
        factory = Mock(return_value=Mock(requests=[]))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report), \
             patch.object(pool, 'verify', return_value=self.verdict):
            pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                          provider_factory=factory)
        audit = {'version': pool.READY_AUDIT_VERSION, 'interesting_hook_score': 3,
                 'evidence_supported': False, 'chronology_consistent': True,
                 'reason': 'The clue adds a causal claim absent from its quotation.'}
        with patch.object(pool, 'audit_ready_interest', return_value=audit):
            result = pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                                   provider_factory=factory)
        self.assertEqual(result['status'], 'audited')
        self.assertEqual(result['ready'], 0)
        with closing(self.connect()) as conn:
            state, verification_text = conn.execute(
                'SELECT state,verification FROM automatic_map_entries').fetchone()
            self.assertEqual(state, 'rejected')
            self.assertTrue(json.loads(verification_text)['hook_rejection'])
            lessons = pool.rejected_interest_lessons(conn)
        self.assertEqual(len(lessons), 1)
        self.assertIn('causal claim', lessons[0]['failure_reason'])

    def test_story_first_navigation_failure_allows_corrected_round_not_identical_retry(self):
        report = {**self.report(), 'pipeline': 'story_first'}
        report['candidate_sha256'] = discovery.digest(report['candidate'])
        factory = Mock(return_value=Mock(requests=[]))
        with patch.dict(os.environ, {'MAP_DISCOVERY_PIPELINE': 'story_first'}), \
             patch.object(pool.map_story_pipeline, 'discover', return_value=report), \
             patch.object(pool, 'verify', return_value=self.verdict):
            pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                          provider_factory=factory)
        audit = {'version': pool.READY_AUDIT_VERSION, 'interesting_hook_score': 5,
                 'evidence_supported': False, 'chronology_consistent': True,
                 'reason': 'The easy map direction is unsupported; the hard story is sound.'}
        with patch.object(pool, 'audit_ready_interest', return_value=audit):
            pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                          provider_factory=factory)
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries').fetchone()[0])
            self.assertTrue(verification['round_rejection'])
            self.assertNotIn('hook_rejection', verification)
            lesson = pool.rejected_interest_lessons(conn)[0]
            self.assertEqual(lesson['rejection_kind'], 'clue_ladder')
            self.assertIn('hook may still be useful', lesson['failure_reason'])
            self.assertEqual(lesson['attempted_clues']['easy'], report['result']['clue_ladder']['easy'])
            with self.assertRaisesRegex(ValueError, 'same rejected Map clue ladder'):
                pool.add(conn, report['candidate'], report['result'], self.verdict,
                         origin='discovery', audit_pending=True)
            corrected = deepcopy(report['result'])
            corrected['clue_ladder']['easy'] = (
                'In northern Brussels, look near the Heysel district, where this landmark stands close '
                'to Heysel/Heizel metro station.')
            pool.add(conn, report['candidate'], corrected, self.verdict,
                     origin='discovery', audit_pending=True)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_rejected_rounds').fetchone()[0], 1)
            with self.assertRaisesRegex(ValueError, 'previously rejected Map clue ladder'):
                pool.add(conn, report['candidate'], report['result'], self.verdict,
                         origin='discovery', audit_pending=True)
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=? WHERE id=?",
                         (json.dumps({**self.verdict, 'editorial_rejection': True,
                                      'round_rejection': 'another unsupported easy clue'}),
                          report['candidate']['id']))
            third = deepcopy(corrected)
            third['clue_ladder']['easy'] = (
                'In Brussels, find the landmark by the Heysel/Heizel metro station, '
                'north of the city centre.')
            pool.add(conn, report['candidate'], third, self.verdict,
                     origin='discovery', audit_pending=True)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_rejected_rounds').fetchone()[0], 2)
            with self.assertRaisesRegex(ValueError, 'previously rejected Map clue ladder'):
                pool.add(conn, report['candidate'], corrected, self.verdict,
                         origin='discovery', audit_pending=True)

    def test_recent_structural_failure_is_reverified_without_new_discovery(self):
        old_report = {**self.report(), 'status': 'failed'}
        report_dir = self.root / 'reports' / 'previous'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery-2026-09-08.json'
        report_path.write_text(json.dumps(old_report), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('old', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'report_path': str(report_path)})),
            )
            conn.commit()
        factory = Mock(return_value=Mock(requests=[]))
        with patch.object(discovery, 'discover') as discover, patch.object(pool, 'verify', return_value=self.verdict):
            outcome = pool.maintain(self.database, self.root / 'reports', seed_catalog=None,
                                    provider_factory=factory)
        self.assertEqual(outcome['status'], 'added')
        self.assertEqual(outcome['retried_report_path'], str(report_path.resolve()))
        discover.assert_not_called()
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automatic_map_entries WHERE state='ready'").fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT source_requests FROM automatic_map_usage').fetchone()[0], 0)

    def test_story_first_failure_cannot_bypass_its_story_gate_via_recovery(self):
        report_dir = self.root / 'reports' / 'previous'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery-2026-09-08.json'
        report_path.write_text(json.dumps({**self.report(), 'status': 'failed',
                                           'pipeline': 'story_first',
                                           'error': 'Hard clue did not preserve the sourced discovery story.'}),
                               encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute('INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                         'VALUES(?,?,?,?,?,?)',
                         ('story-failed', '2026-09-08', '2026-09-08', self.clock.isoformat(),
                          'failed', json.dumps({'report_path': str(report_path)})))
            conn.commit()
            self.assertIsNone(pool.recoverable_report(conn, self.root / 'reports', '2026-09-08'))

    def test_failed_report_reverification_is_attempted_only_once(self):
        old_report = {**self.report(), 'status': 'failed'}
        report_dir = self.root / 'reports' / 'previous'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery-2026-09-08.json'
        report_path.write_text(json.dumps(old_report), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('old', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'report_path': str(report_path)})),
            )
            conn.commit()
        with patch.object(discovery, 'discover') as discover, patch.object(
            pool, 'verify', side_effect=ValueError('Weak place hook')
        ):
            first = pool.maintain(self.database, self.root / 'reports', seed_catalog=None,
                                  provider_factory=Mock(return_value=Mock(requests=[])))
            self.assertEqual(first['status'], 'failed')
            self.assertEqual(first['retried_report_path'], str(report_path.resolve()))
            discover.assert_not_called()
        fresh_failure = {'status': 'failed', 'error': 'No source.', 'rejections': []}
        with patch.object(discovery, 'discover', return_value=fresh_failure) as discover:
            pool.maintain(self.database, self.root / 'reports', seed_catalog=None,
                          provider_factory=Mock(return_value=Mock(requests=[])))
        discover.assert_called_once()

    def test_recovery_will_not_read_a_report_outside_its_private_directory(self):
        outside = self.root / 'outside.json'
        outside.write_text(json.dumps({**self.report(), 'status': 'failed'}), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('old', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'report_path': str(outside)})),
            )
            conn.commit()
            self.assertIsNone(pool.recoverable_report(conn, self.root / 'reports', '2026-09-08'))

    def test_recent_failed_round_is_replayed_with_reason_from_private_report(self):
        report_dir = self.root / 'reports' / 'previous'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery-2026-09-08.json'
        report_path.write_text(json.dumps(self.report()), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('failed-hook', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'report_path': str(report_path),
                             'reason': 'Evidence verifier rejected: the hook was minor trivia.'})),
            )
            conn.commit()
            lessons = pool.recent_failed_round_lessons(conn, self.root / 'reports')
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]['attempted_clues']['hard'], self.result['clue_ladder']['hard'])
        self.assertIn('minor trivia', lessons[0]['failure_reason'])

        rejected_report = self.report()
        rejected_report.pop('candidate')
        rejected_report.pop('result')
        report_path.write_text(json.dumps(rejected_report), encoding='utf-8')
        with closing(self.connect()) as conn:
            rejected_lessons = pool.recent_failed_round_lessons(conn, self.root / 'reports')
        self.assertEqual(rejected_lessons[0]['place'], self.place['canonical_name'])

        provider = Mock()
        ids = [p['id'] for p in discovery.evidence_units(self.report()['resolved_candidates'][0])]
        provider.call_with_fallback.return_value = {
            **self.verdict,
            'levels': {k: {'supported': True, 'source_ids': ids} for k in controlled.LEVELS},
            'reason': 'Verified.',
        }
        pool.verify(self.report(), provider, failure_lessons=lessons)
        self.assertIn('minor trivia', provider.call_with_fallback.call_args.kwargs['prompt'])

    def test_failed_discovery_never_enters_ready_pool_and_remembers_rejections(self):
        failed = {'status': 'failed', 'error': 'No source.', 'rejections': [{'title': 'Unresolved place'}]}
        with patch.object(discovery, 'discover', return_value=failed), patch.object(pool, 'verify') as verify:
            result = pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertEqual(result['status'], 'failed')
        verify.assert_not_called()
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_entries').fetchone()[0], 0)
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertIn('Unresolved place', discover.call_args.kwargs['excluded_names'])

    def test_legacy_budget_exhaustion_does_not_exclude_unchecked_places(self):
        report_dir = self.root / 'reports' / 'run1'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery.json'
        report_path.write_text(json.dumps({'rejections': [
            {'title': 'Bad source', 'reason': 'Missing source page.'},
            {'title': 'Unexamined place', 'reason': 'Target article: Automatic map request budget exhausted.'},
            {'title': 'Inherited failure', 'reason': 'Place was rejected recently; choose a new candidate.'},
        ]}), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('run1', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'failed_names': ['Bad source', 'Bad source', 'Unexamined place', 'Inherited failure'],
                             'report_path': str(report_path)})),
            )
            conn.commit()
            self.assertEqual(pool.recent_failed_names(conn, self.root / 'reports'), ['Bad source'])

    def test_bad_map_anchor_teaches_next_proposal_without_blacklisting_landmark(self):
        report_dir = self.root / 'reports' / 'route-failure'
        report_dir.mkdir(parents=True)
        report_path = report_dir / 'discovery.json'
        report_path.write_text(json.dumps({'rejections': [
            {'title': 'Himeji Castle', 'reason': 'Local feature article: Missing source page.'},
            {'title': 'Tower Bridge', 'reason': 'Search area centres are too close to the answer or too far away.'},
            {'title': 'Bad coordinate', 'reason': 'Wikipedia and Wikidata coordinates disagree by more than 250 metres.'},
        ]}), encoding='utf-8')
        with closing(self.connect()) as conn:
            conn.execute(
                'INSERT INTO automatic_map_runs(id,budget_day,target_date,started_at,status,detail) '
                'VALUES(?,?,?,?,?,?)',
                ('route-failure', '2026-09-08', '2026-09-08', self.clock.isoformat(), 'failed',
                 json.dumps({'failed_names': ['Himeji Castle', 'Tower Bridge', 'Bad coordinate'],
                             'report_path': str(report_path)})),
            )
            conn.commit()
            self.assertEqual(pool.recent_failed_names(conn, self.root/'reports'), ['Bad coordinate'])
            lessons = pool.recent_route_failure_lessons(conn, self.root/'reports')
        self.assertEqual([item['place'] for item in lessons], ['Himeji Castle', 'Tower Bridge'])
        failed = {'status': 'failed', 'error': 'No source.', 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            pool.maintain(self.database, self.root/'reports', seed_catalog=None,
                          provider_factory=Mock(return_value=Mock(requests=[])))
        self.assertEqual(discover.call_args.kwargs['route_failure_lessons'], lessons)
        self.assertNotIn('Himeji Castle', discover.call_args.kwargs['excluded_names'])

    def test_operator_rejected_hook_teaches_generator_and_allows_new_hook(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT verification FROM automatic_map_entries WHERE id=?', (self.place['id'],)).fetchone()
            verification = json.loads(row[0])
            verification['operator_rejection'] = {'reason': 'The place hook is not compelling.', 'scope': 'hook', 'at': self.clock.isoformat()}
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=? WHERE id=?",
                         (json.dumps(verification), self.place['id']))
            conn.commit()
            feedback = pool.editorial_corrections(conn)
            self.assertEqual(feedback[0]['rejected_hook'], self.result['clue_ladder']['hard'])
            self.assertTrue(feedback[0]['negative_only'])
            self.assertIn('not compelling', pool.rejected_interest_lessons(conn)[0]['failure_reason'])
            with self.assertRaisesRegex(ValueError, 'same operator-rejected Map hook'):
                pool.add(conn, self.place, self.result, self.verdict, origin='discovery')
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries WHERE id=?',
                                          (self.place['id'],)).fetchone()[0], 'rejected')
        failed = {'status': 'failed', 'error': 'No source.', 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertNotIn(self.place['id'], [place['id'] for place in discover.call_args.kwargs['excluded_places']])
        self.assertIn(feedback[0], discover.call_args.kwargs['editorial_feedback'])
        replacement = deepcopy(self.result)
        replacement['clue_ladder']['hard'] = ('Visitors can dine in an upper sphere while looking '
                                               'across Brussels from this unusual exhibition building.')
        with closing(self.connect()) as conn:
            with patch.object(controlled, 'validate_result', return_value={**replacement, 'automated_pass': True}):
                pool.add(conn, self.place, replacement, self.verdict, origin='discovery')
            conn.commit()
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries WHERE id=?',
                                          (self.place['id'],)).fetchone()[0], 'ready')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_rejected_hooks WHERE place_id=?',
                                          (self.place['id'],)).fetchone()[0], 1)
            self.assertEqual(pool.editorial_corrections(conn)[0]['rejected_hook'],
                             self.result['clue_ladder']['hard'])

    def test_rejected_story_paraphrase_is_blocked_before_another_model_audit(self):
        old = ('This site marks where Mumtaz Mahal was first buried before moving to the main '
               'mausoleum chamber, featuring a Persian-inspired charbagh garden.')
        new = ('The north-western quadrant marks the site where Mumtaz Mahal was first buried '
               'before moving to the main chamber.')
        other = ('A team of stonecutters built a marble dome with a remarkable double-shell design.')
        self.assertTrue(pool.same_rejected_story(old, new))
        self.assertFalse(pool.same_rejected_story(old, other))
        self.assertFalse(pool.same_rejected_story('A short clue.', 'Another short clue.'))

        self.queue('discovery')
        paraphrase = deepcopy(self.result)
        paraphrase['clue_ladder']['hard'] = ('Built for Expo 58, this walk-in iron crystal magnifies '
                                               'an atomic structure 165 billion times into a building.')
        with closing(self.connect()) as conn:
            verification = {**self.verdict, 'interesting_hook_score': 2,
                            'hook_rejection': 'ready audit rejected a weak discovery hook'}
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=? WHERE id=?",
                         (json.dumps(verification), self.place['id']))
            conn.commit()
            history = pool.rejected_story_hooks(conn, self.place['id'])
            self.assertEqual(history, [self.result['clue_ladder']['hard']])
            with self.assertRaisesRegex(ValueError, 'earlier rejected story'):
                pool.add(conn, self.place, paraphrase, self.verdict, origin='discovery')
        provider = Mock()
        with patch.object(discovery, 'validate_selection', return_value=(self.place, paraphrase)):
            with self.assertRaisesRegex(ValueError, 'earlier rejected story'):
                pool.verify(self.report(), provider, rejected_hooks=history)
        provider.call_with_fallback.assert_not_called()

    def test_operator_rejected_place_stays_excluded(self):
        self.queue('discovery')
        with closing(self.connect()) as conn:
            verification = json.loads(conn.execute('SELECT verification FROM automatic_map_entries WHERE id=?',
                                                   (self.place['id'],)).fetchone()[0])
            verification['operator_rejection'] = {'reason': 'This place itself is unsuitable for a light game.',
                                                  'scope': 'place', 'at': self.clock.isoformat()}
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=? WHERE id=?",
                         (json.dumps(verification), self.place['id']))
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'explicit operator review'):
                pool.add(conn, self.place, self.result, self.verdict, origin='discovery')
        with patch.object(discovery, 'discover', return_value={'status': 'failed', 'error': 'No source.', 'rejections': []}) as discover:
            pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertIn(self.place['id'], [place['id'] for place in discover.call_args.kwargs['excluded_places']])

    def test_failed_evidence_review_blocks_automatic_admission(self):
        with patch.object(discovery, 'discover', return_value=self.report()), patch.object(pool, 'verify', side_effect=ValueError('unsupported qualifier')):
            result = pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock(return_value=Mock(requests=[])))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('unsupported qualifier', result['reason'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_entries').fetchone()[0], 0)

    def test_clue_format_failure_does_not_blacklist_source_resolved_place(self):
        place = {'id': 'q123', 'canonical_name': 'Viable landmark'}
        failed = {'status': 'failed', 'error': 'Clues must be concise single-line plain text.',
                  'model_output': {'place_id': 'q123'}, 'resolved_candidates': [place], 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed):
            first = pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertEqual(first['status'], 'failed')
        self.assertEqual(first['failed_names'], [])
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock())
        self.assertNotIn('Viable landmark', discover.call_args.kwargs['excluded_names'])

    def test_initial_reserve_is_one_time_and_missing_key_does_not_burn_budget(self):
        with patch.dict(os.environ, {}, clear=True):
            first = pool.maintain(self.database, self.root)
            self.assertEqual(first['status'], 'deferred')
            with closing(self.connect()) as conn:
                count = conn.execute('SELECT COUNT(*) FROM automatic_map_entries').fetchone()[0]
                self.assertGreater(count, 0)
                conn.execute("UPDATE automatic_map_entries SET state='used'")
                conn.commit()
            pool.maintain(self.database, self.root)
            with closing(self.connect()) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM automatic_map_entries WHERE state='ready'").fetchone()[0], 0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_runs').fetchone()[0], 0)

    def test_server_automatic_path_does_not_invoke_old_generator(self):
        import server
        self.queue()
        with closing(self.connect()) as conn, patch.object(server, 'DAILY_MAP_AUTOMATIC_ENABLED', True), \
             patch.object(server, 'DAILY_MAP_AI_GENERATION_ENABLED', True), \
             patch.object(controlled, 'generate_and_publish') as old:
            result = server.generate_daily_map_game_for_date(conn, puzzle_date='2026-09-08')
            self.assertEqual(result['status'], 'published')
            old.assert_not_called()
            self.assertEqual(server.generate_daily_map_game_for_date(conn, puzzle_date='2026-09-08', force=True)['status'], 'published')

    def test_missing_learning_profile_defers_without_requests(self):
        factory = Mock()
        with patch.object(pool.daily_map_game, 'map_learning_profile_hash', return_value=''):
            outcome = pool.maintain(self.database, self.root, provider_factory=factory)
        self.assertEqual(outcome['status'], 'deferred')
        factory.assert_not_called()
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_runs').fetchone()[0], 0)

    def test_automatic_fallback_preserves_round_published_by_another_connection(self):
        import server
        self.queue()
        published = {}

        def competing_publication(conn, *, puzzle_date):
            with closing(self.connect()) as competing:
                controlled.publish_validated_round(
                    competing, puzzle_date=puzzle_date, place=self.place, result=self.result,
                    provider_name='test-competing-publication',
                )
                competing.commit()
                published['puzzle'] = tuple(competing.execute('SELECT * FROM daily_map_puzzles').fetchone())
                published['level'] = tuple(competing.execute('SELECT * FROM daily_map_levels').fetchone())
            # The automatic publisher's transaction recheck sees the competing publication.
            controlled.eligible_places_in_database(conn, puzzle_date, [self.place])

        with closing(self.connect()) as conn, patch.object(server, 'DAILY_MAP_AUTOMATIC_ENABLED', True), \
             patch.object(server, 'DAILY_MAP_AI_GENERATION_ENABLED', True), \
             patch.object(pool, 'publish', side_effect=competing_publication):
            result = server.generate_daily_map_game_for_date(conn, puzzle_date='2026-09-08')
            self.assertEqual(result['status'], 'published')
            self.assertEqual(tuple(conn.execute('SELECT * FROM daily_map_puzzles').fetchone()), published['puzzle'])
            self.assertEqual(tuple(conn.execute('SELECT * FROM daily_map_levels').fetchone()), published['level'])
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'ready')

    def test_stocked_queue_stops_requests_and_expiry_reopens_maintenance(self):
        self.queue()
        factory = Mock()
        with patch.object(pool, 'TARGET_READY', 1):
            self.assertEqual(pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=factory)['status'], 'stocked')
        factory.assert_not_called()
        self.clock += timedelta(days=pool.MAX_AGE_DAYS + 1)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(pool.maintain(self.database, self.root, seed_catalog=None)['status'], 'deferred')
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT state FROM automatic_map_entries').fetchone()[0], 'expired')

    def test_maintenance_cycle_keeps_generating_until_queue_target(self):
        with patch.object(pool, 'TARGET_READY', 2), patch.object(
            pool,
            'maintain',
            side_effect=[
                {'status': 'added', 'ready': 1, 'place': 'First'},
                {'status': 'added', 'ready': 2, 'place': 'Second'},
            ],
        ) as maintain:
            result = pool.maintain_until_stocked(
                self.database,
                self.root,
                seed_catalog=None,
                max_attempts=4,
            )

        self.assertEqual(result['status'], 'stocked')
        self.assertEqual(result['ready'], 2)
        self.assertEqual(result['attempted'], 2)
        self.assertEqual(maintain.call_count, 2)

    def test_maintenance_cycle_continues_promptly_without_a_quota_error(self):
        with patch.object(pool, 'TARGET_READY', 7), patch.object(
            pool,
            'maintain',
            return_value={'status': 'failed', 'ready': 0, 'reason': 'candidate rejected'},
        ) as maintain:
            result = pool.maintain_until_stocked(
                self.database,
                self.root,
                seed_catalog=None,
                max_attempts=4,
            )

        self.assertEqual(result['status'], 'replenishing')
        self.assertEqual(result['attempted'], 4)
        self.assertEqual(result['retry_at'], '2026-09-08T10:00:15+00:00')
        self.assertEqual(maintain.call_count, 4)

        self.clock += timedelta(seconds=16)
        with patch.object(pool, 'maintain', return_value={'status': 'stocked', 'ready': 7}) as maintain:
            resumed = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
        self.assertEqual(resumed['status'], 'stocked')
        maintain.assert_called_once()

    def test_provider_quota_uses_reported_retry_delay(self):
        with patch.object(
            pool,
            'maintain',
            return_value={
                'status': 'failed',
                'ready': 3,
                'reason': 'RESOURCE_EXHAUSTED free_tier_requests; free-models-per-day',
                'retry_after_seconds': 125,
            },
        ):
            result = pool.maintain_until_stocked(
                self.database,
                self.root,
                seed_catalog=None,
            )

        self.assertEqual(result['status'], 'quota_paused')
        self.assertEqual(result['retry_at'], '2026-09-08T10:02:10+00:00')

    def test_provider_reset_pause_survives_scheduler_ticks_and_restart(self):
        quota = {
            'status': 'failed', 'ready': 3,
            'reason': 'RESOURCE_EXHAUSTED free_tier_requests; free-models-per-day',
            'retry_after_seconds': 125,
        }
        with patch.object(pool, 'maintain', return_value=quota) as maintain:
            first = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
            self.assertEqual(maintain.call_count, 1)
        with patch.object(pool, 'maintain') as maintain:
            second = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
            self.assertEqual(second['status'], 'quota_paused')
            self.assertEqual(second['retry_at'], first['retry_at'])
            self.assertEqual(second['attempted'], 0)
            maintain.assert_not_called()
        self.clock += timedelta(seconds=131)
        with patch.object(pool, 'maintain', return_value={'status': 'stocked', 'ready': 7}) as maintain:
            resumed = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
            self.assertEqual(resumed['status'], 'stocked')
            maintain.assert_called_once()
        with closing(self.connect()) as conn:
            self.assertIsNone(conn.execute(
                "SELECT value FROM automatic_map_meta WHERE key='provider_retry'"
            ).fetchone())

    def test_provider_quota_failure_stops_refill_cycle_without_more_attempts(self):
        failed = {'status': 'failed',
                  'error': 'All AI providers failed: RESOURCE_EXHAUSTED free_tier_requests; free-models-per-day',
                  'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            result = pool.maintain_until_stocked(
                self.database, self.root/'reports', seed_catalog=None,
                provider_factory=Mock(return_value=Mock(requests=[])), max_attempts=4,
            )
        self.assertEqual(result['status'], 'quota_paused')
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['retry_at'], '2026-09-08T10:30:05+00:00')
        discover.assert_called_once()

    def test_provider_report_retry_hint_survives_discovery_failure(self):
        failed = {'status': 'failed', 'error': 'Map preview provider failed; stopped to preserve quota.',
                  'provider_error_detail': 'Gemini request failed with HTTP 429: RESOURCE_EXHAUSTED free-models-per-day',
                  'retry_after_seconds': 3600, 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed):
            result = pool.maintain_until_stocked(
                self.database, self.root/'reports', seed_catalog=None,
                provider_factory=Mock(return_value=Mock(requests=[])), max_attempts=4,
            )
        self.assertTrue(result['quota_limited'])
        self.assertEqual(result['retry_at'], '2026-09-08T11:00:05+00:00')

    def test_verifier_quota_error_uses_its_own_reset_delay(self):
        discovery_provider = Mock(requests=[], provider_error_detail='', retry_after_seconds=None)
        verifier_provider = Mock(
            requests=[], provider_error_detail='RESOURCE_EXHAUSTED free-models-per-day',
            retry_after_seconds=3600,
        )
        factory = Mock(side_effect=[discovery_provider, verifier_provider])
        with patch.object(discovery, 'discover', return_value=self.report()), \
             patch.object(pool, 'verify', side_effect=RuntimeError('Map provider stopped')):
            result = pool.maintain_until_stocked(
                self.database, self.root, seed_catalog=None, provider_factory=factory,
            )
        self.assertEqual(result['status'], 'quota_paused')
        self.assertEqual(result['retry_at'], '2026-09-08T11:00:05+00:00')

    def test_provider_503_pauses_refill_and_resumes_after_reported_delay(self):
        failed = {'status': 'failed',
                  'error': 'Map preview provider failed; stopped to preserve quota.',
                  'provider_error_detail': 'Gemini request failed with HTTP 503: UNAVAILABLE',
                  'retry_after_seconds': 125, 'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            first = pool.maintain_until_stocked(
                self.database, self.root/'reports', seed_catalog=None,
                provider_factory=Mock(return_value=Mock(requests=[])), max_attempts=4,
            )
        self.assertEqual(first['status'], 'provider_paused')
        self.assertEqual(first['attempted'], 1)
        self.assertEqual(first['retry_at'], '2026-09-08T10:02:10+00:00')
        discover.assert_called_once()
        with patch.object(pool, 'maintain') as maintain:
            paused = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
        self.assertEqual(paused['status'], 'provider_paused')
        self.assertEqual(paused['attempted'], 0)
        maintain.assert_not_called()
        self.clock += timedelta(seconds=131)
        with patch.object(pool, 'maintain', return_value={'status': 'stocked', 'ready': 7}) as maintain:
            resumed = pool.maintain_until_stocked(self.database, self.root, seed_catalog=None)
        self.assertEqual(resumed['status'], 'stocked')
        maintain.assert_called_once()

    def test_provider_503_without_retry_hint_uses_bounded_backoff(self):
        failed = {'status': 'failed', 'error': 'Gemini request failed with HTTP 503: UNAVAILABLE',
                  'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed):
            result = pool.maintain_until_stocked(
                self.database, self.root/'reports', seed_catalog=None,
                provider_factory=Mock(return_value=Mock(requests=[])), max_attempts=4,
            )
        self.assertEqual(result['status'], 'provider_paused')
        self.assertEqual(result['retry_at'], '2026-09-08T10:30:05+00:00')

    def test_provider_timeout_pauses_instead_of_repeating_free_tier_requests(self):
        failed = {'status': 'failed',
                  'error': 'Map preview provider failed; stopped to preserve quota.',
                  'provider_error_detail': 'Gemini request failed: The read operation timed out',
                  'rejections': []}
        with patch.object(discovery, 'discover', return_value=failed) as discover:
            result = pool.maintain_until_stocked(
                self.database, self.root/'reports', seed_catalog=None,
                provider_factory=Mock(return_value=Mock(requests=[])), max_attempts=4,
            )
        self.assertEqual(result['status'], 'provider_paused')
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['retry_at'], '2026-09-08T10:30:05+00:00')
        discover.assert_called_once()

    def test_verifier_503_uses_verifier_retry_hint(self):
        discovery_provider = Mock(requests=[], provider_error_detail='', retry_after_seconds=None)
        verifier_provider = Mock(
            requests=[], provider_error_detail='Gemini request failed with HTTP 503: UNAVAILABLE',
            retry_after_seconds=3600,
        )
        factory = Mock(side_effect=[discovery_provider, verifier_provider])
        with patch.object(discovery, 'discover', return_value=self.report()), \
             patch.object(pool, 'verify', side_effect=RuntimeError('Map provider stopped')):
            result = pool.maintain_until_stocked(
                self.database, self.root, seed_catalog=None, provider_factory=factory,
            )
        self.assertEqual(result['status'], 'provider_paused')
        self.assertFalse(result['quota_limited'])
        self.assertEqual(result['retry_at'], '2026-09-08T11:00:05+00:00')

    def test_scheduler_wakes_for_maintenance_even_when_games_are_published(self):
        import server
        with patch.object(server, 'DAILY_MAP_AUTOMATIC_ENABLED', True), \
             patch.object(server, 'DAILY_MAP_AI_GENERATION_ENABLED', True), \
             patch.object(server, 'ensure_active_daily_map_games', return_value=[{'status': 'published'}]), \
             patch.object(server, 'next_daily_map_game_run', return_value=datetime.now(timezone.utc) + timedelta(days=1)), \
             patch.object(server.time, 'sleep', side_effect=InterruptedError) as sleep:
            with self.assertRaises(InterruptedError):
                server.daily_map_game_scheduler_loop()
        self.assertLessEqual(sleep.call_args.args[0], 900)


if __name__ == '__main__':
    unittest.main()
