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
        self.verdict = {k: True for k in pool.CHECKS}

    def connect(self):
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def queue(self, origin='bootstrap'):
        with closing(self.connect()) as conn:
            pool.add(conn, self.place, self.result, self.verdict, origin=origin)
            conn.commit()

    def test_budget_is_by_actual_day_not_future_game_date_and_survives_restart(self):
        for index in range(4):
            budget = pool.Budget(self.database, f'2026-10-{index+1:02d}')
            self.assertEqual(budget.attempt_number, index + 1)
            for _ in range(3):
                budget.spend('model')
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                budget.spend('model')
            budget.complete('failed', {})
        with self.assertRaisesRegex(ValueError, 'daily budget'):
            pool.Budget(self.database, '2026-12-01')
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT day,attempts,model_requests FROM automatic_map_usage').fetchone()
            self.assertEqual(tuple(row), ('2026-09-08', 4, 12))
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

    def test_source_request_cap_rolls_back_partial_daily_increment(self):
        budget = pool.Budget(self.database, '2026-09-08')
        for _ in range(16):
            budget.spend('source')
        with self.assertRaises(ValueError):
            budget.spend('source')
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT source_requests FROM automatic_map_usage').fetchone()[0], 16)

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
        self.clock += timedelta(days=15)
        with closing(self.connect()) as conn, self.assertRaisesRegex(ValueError, 'No eligible'):
            pool.publish(conn, puzzle_date='2026-09-23')
        self.clock -= timedelta(days=15)
        with closing(self.connect()) as conn:
            changed = deepcopy(self.result)
            changed['clue_ladder']['hard'] = 'A changed clue that has not been through the verification step.'
            conn.execute('UPDATE automatic_map_entries SET result=?', (json.dumps(changed),))
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'checked payload'):
                pool.publish(conn, puzzle_date='2026-09-08')

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

    def test_independent_verifier_rejects_unsupported_or_fabricated_citations(self):
        report = self.report()
        ids = [p['id'] for p in discovery.evidence_units(report['resolved_candidates'][0])]
        verdict = {**self.verdict, 'levels': {k: {'supported': True, 'source_ids': ids} for k in controlled.LEVELS}, 'reason': 'Supported by supplied passages.'}
        provider = Mock()
        provider.call_with_fallback.return_value = verdict
        self.assertEqual(pool.verify(report, provider), verdict)
        for change in ('unsupported', 'citation', 'uncertain'):
            altered = deepcopy(verdict)
            if change == 'unsupported': altered['levels']['hard']['supported'] = False
            if change == 'citation': altered['levels']['hard']['source_ids'] = ['invented']
            if change == 'uncertain': altered['identity_correct'] = 'true'
            provider.call_with_fallback.return_value = altered
            with self.subTest(change=change), self.assertRaises(ValueError):
                pool.verify(report, provider)

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

    def test_failed_evidence_review_blocks_automatic_admission(self):
        with patch.object(discovery, 'discover', return_value=self.report()), patch.object(pool, 'verify', side_effect=ValueError('unsupported qualifier')):
            result = pool.maintain(self.database, self.root, seed_catalog=None, provider_factory=Mock(return_value=Mock(requests=[])))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('unsupported qualifier', result['reason'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM automatic_map_entries').fetchone()[0], 0)

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
        self.clock += timedelta(days=15)
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

    def test_maintenance_cycle_waits_for_reset_after_attempt_cap(self):
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

        self.assertEqual(result['status'], 'attempt_cap')
        self.assertEqual(result['attempted'], 4)
        self.assertEqual(result['retry_at'], '2026-09-09T00:05:00+00:00')
        self.assertEqual(maintain.call_count, 4)

    def test_daily_budget_defer_reports_provider_wake_time(self):
        with patch.object(
            pool,
            'maintain',
            return_value={
                'status': 'deferred',
                'ready': 3,
                'reason': 'Automatic map daily budget exhausted.',
            },
        ):
            result = pool.maintain_until_stocked(
                self.database,
                self.root,
                seed_catalog=None,
            )

        self.assertEqual(result['status'], 'capped')
        self.assertEqual(result['retry_at'], '2026-09-09T00:05:00+00:00')

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
