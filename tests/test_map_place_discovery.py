from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import discover_map_places as discovery
from tools import controlled_map_round as controlled


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.place = deepcopy(next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG) if p['id'] == 'atomium'))
        self.place['retrieved_on'] = discovery.date.today().isoformat()
        self.place['sources']['article'] = next(iter(self.place['sources'].values()))
        text = ' '.join(f['text'] for f in self.place['facts'].values())
        self.place['evidence'] = {'article': {'text': text}}
        self.payload = {'place_id': self.place['id'], 'selection_reason': 'A memorable engineering idea makes a recognisable landmark.',
                        'facts': {level: {'quote': fact['text'], 'text': fact['text']} for level, fact in self.place['facts'].items()},
                        'clues': {level: {'text': fact['text'], 'fact_id': level} for level, fact in self.place['facts'].items()}}

    def budget(self):
        return discovery.RunBudget(self.root / 'budget.db', '2026-09-10')

    def second_place(self):
        place = deepcopy(next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG) if p['id'] == 'eiffel-tower'))
        place['retrieved_on'] = discovery.date.today().isoformat()
        place['sources']['article'] = next(iter(place['sources'].values()))
        place['evidence'] = {'article': {'text': ' '.join(f['text'] for f in place['facts'].values())}}
        return place

    def test_proposal_focus_rotates_geographic_lanes_without_more_model_requests(self):
        self.assertGreaterEqual(discovery.MAX_SOURCE_REQUESTS, discovery.PROPOSAL_COUNT * 10)
        focuses = [
            discovery.proposal_focus(Mock(day='2026-10-02', budget_day='2026-10-01', attempt_number=number))
            for number in range(1, 5)
        ]
        self.assertEqual(len(set(focuses)), 4)
        self.assertEqual(set(focuses), set(discovery.PROPOSAL_FOCUSES))
        next_day = discovery.proposal_focus(Mock(day='2026-10-02', budget_day='2026-10-02', attempt_number=1))
        self.assertNotEqual(next_day, focuses[0])

    def test_exclusion_keys_keep_non_latin_places_distinct(self):
        self.assertEqual(discovery.exclusion_key('St. Paul'), discovery.exclusion_key('Saint Paul'))
        self.assertEqual(discovery.exclusion_key('故宫'), '故宫')
        self.assertNotEqual(discovery.exclusion_key('故宫'), discovery.exclusion_key('東京塔'))
        discovery.reject_excluded_place(['東京塔'], ['故宫'])
        with self.assertRaisesRegex(ValueError, 'rejected recently'):
            discovery.reject_excluded_place(['故宫'], ['故宫'])

    def test_budget_survives_restart_and_counts_attempt_before_transport(self):
        budget = self.budget()
        budget.spend('model')
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.budget()
        budget.spend('model')
        budget.spend('model')
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            budget.spend('model')
        self.assertEqual(budget.finish('failed', self.root / 'report.json')['model_requests'], 3)
        with self.assertRaises(ValueError):
            budget.spend('source')

    def test_source_allowlist_redirect_and_response_size(self):
        source = discovery.WikimediaSource(self.budget())
        with self.assertRaises(ValueError):
            source.request('127.0.0.1', {})
        with patch.object(discovery.http.client, 'HTTPSConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 302
            with self.assertRaisesRegex(RuntimeError, '302'):
                source.request('en.wikipedia.org', {})
            connection.return_value.close.assert_called()
            response.status = 200
            response.read.return_value = b'x' * (discovery.MAX_RESPONSE_BYTES + 1)
            with self.assertRaisesRegex(ValueError, 'size limit'):
                source.request('en.wikipedia.org', {})

    def test_titles_cannot_inject_urls_namespaces_or_api_parameters(self):
        for value in ('https://127.0.0.1/', 'File:example', 'Berlin|Paris', 'Paris\nHost: x', '../secret', '&lt;script&gt;'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                discovery.title(value)
        self.assertEqual(discovery.title('Edinburgh Castle'), 'Edinburgh Castle')
        self.assertEqual(discovery.title('Great Mosque of Djenn&eacute;'), 'Great Mosque of Djenné')

    def test_missing_source_title_accepts_only_equivalent_article(self):
        source = discovery.WikimediaSource(self.budget())
        def page(name):
            if name == 'Hillerød':
                return {'title': name}
            raise ValueError('Missing source page.')
        with patch.object(source, 'page', side_effect=page), \
             patch.object(source, 'equivalent_titles', return_value=['Hillerød', 'Hillerod Castle']) as search:
            self.assertEqual(discovery.resolved_page(source, 'Hillerod')['title'], 'Hillerød')
        search.assert_called_once_with('Hillerod')
        with patch.object(source, 'page', side_effect=ValueError('Missing source page.')), \
             patch.object(source, 'equivalent_titles', return_value=['Bran (village)', 'Bran Castle']):
            with self.assertRaisesRegex(ValueError, 'equivalent source article'):
                discovery.resolved_page(source, 'Bran')

    def test_equivalent_title_search_is_main_namespace_and_bounded(self):
        source = discovery.WikimediaSource(self.budget())
        with patch.object(source, 'request', return_value={'query': {'search': [
                {'title': 'Hillerød'}, {'title': 'Hillerod Castle'}]}}) as request:
            self.assertEqual(source.equivalent_titles('Hillerod'), ['Hillerød', 'Hillerod Castle'])
        self.assertEqual(request.call_args.args[0], 'en.wikipedia.org')
        self.assertEqual(request.call_args.args[1]['srnamespace'], 0)
        self.assertEqual(request.call_args.args[1]['srlimit'], 5)

    def test_entity_request_includes_revision_metadata_for_pinned_sources(self):
        source = discovery.WikimediaSource(self.budget())
        def response(host, params):
            self.assertEqual(host, 'www.wikidata.org')
            self.assertIn('info', params['props'].split('|'))
            return {'entities': {'Q100': {'lastrevid': 12345}}}
        with patch.object(source, 'request', side_effect=response):
            self.assertEqual(source.entities(['Q100'])['Q100']['lastrevid'], 12345)

    def test_article_fetch_does_not_use_truncating_extract_parameter(self):
        source = discovery.WikimediaSource(self.budget())
        article = 'A landmark with recorded history. ' * 220 + 'Beside Local Park.'
        def response(host, params):
            self.assertNotIn('exchars', params)
            return {'query': {'pages': [{'ns': 0, 'title': 'Example', 'lastrevid': 123,
                     'extract': article, 'pageprops': {'wikibase_item': 'Q100'},
                     'coordinates': [{'lat': 50, 'lon': 1, 'globe': 'earth'}]}]}}
        with patch.object(source, 'request', side_effect=response):
            self.assertIn('Local Park', source.page('Example')['text'])

    def test_area_intro_batch_saves_a_request_without_truncating_target_evidence(self):
        source = discovery.WikimediaSource(self.budget())
        def page(name, entity, text):
            return {'ns': 0, 'title': name, 'lastrevid': 123, 'extract': text,
                    'pageprops': {'wikibase_item': entity},
                    'coordinates': [{'lat': 50, 'lon': 1, 'globe': 'earth'}]}
        area_text = 'This settlement has a documented location and history. ' * 4
        area_result = {'query': {
            'normalized': [{'from': 'city_name', 'to': 'City name'}],
            'redirects': [{'from': 'Old Park', 'to': 'Park'}],
            'pages': [page('City name', 'Q101', area_text), page('Park', 'Q102', area_text)],
        }}
        target_text = 'A full target article with distinct historical evidence. ' * 4
        with patch.object(source, 'request', side_effect=[area_result, {'query': {'pages': [
                page('Old Park', 'Q102', target_text)]}}]) as request:
            source.prefetch_area_pages(['city_name', 'Old Park'])
            self.assertEqual(source.area_page('city_name')['title'], 'City name')
            self.assertEqual(source.area_page('Old Park')['title'], 'Park')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(source.page('Old Park')['text'], discovery.normalized(target_text))
            self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[1]['exlimit'], 2)
        self.assertEqual(request.call_args_list[0].args[1]['exintro'], 1)
        self.assertNotIn('exintro', request.call_args_list[1].args[1])

    def test_short_area_intro_falls_back_to_full_article_validation(self):
        source = discovery.WikimediaSource(self.budget())
        def page(name, entity, text):
            return {'ns': 0, 'title': name, 'lastrevid': 123, 'extract': text,
                    'pageprops': {'wikibase_item': entity},
                    'coordinates': [{'lat': 50, 'lon': 1, 'globe': 'earth'}]}
        long_text = 'A sufficiently detailed article about this named location. ' * 4
        with patch.object(source, 'request', side_effect=[
                {'query': {'pages': [page('City', 'Q101', long_text), page('Park', 'Q102', 'Short')]}},
                {'query': {'pages': [page('Park', 'Q102', long_text)]}},
        ]) as request:
            source.prefetch_area_pages(['City', 'Park'])
            self.assertEqual(source.area_page('City')['title'], 'City')
            self.assertEqual(source.area_page('Park')['title'], 'Park')
            self.assertEqual(request.call_count, 2)

    def test_source_distinguishes_missing_and_ambiguous_articles(self):
        source = discovery.WikimediaSource(self.budget())
        for page, message in (({'missing': True}, 'Missing source page'),
                              ({'ns': 0, 'pageprops': {'disambiguation': ''}}, 'Ambiguous source page')):
            with self.subTest(message=message), patch.object(source, 'request', return_value={'query': {'pages': [page]}}):
                with self.assertRaisesRegex(ValueError, message):
                    source.page('Example')

    def test_title_retry_is_bounded_and_never_uses_fuzzy_or_unsourced_matches(self):
        source = Mock()
        pages = {'Corcovado': {'title': 'Corcovado'},
                 'Millennium Bridge, London': {'title': 'Millennium Bridge, London'}}
        def page(name):
            if name in pages:
                return pages[name]
            if name == 'Corcovado (mountain)' or name == 'Himeji Park':
                raise ValueError('Missing source page.')
            raise ValueError('Ambiguous source page.')
        source.page.side_effect = page
        self.assertEqual(discovery.resolved_page(source, 'Corcovado (mountain)')['title'], 'Corcovado')
        self.assertEqual(discovery.resolved_page(source, 'Millennium Bridge', city_hint='London')['title'],
                         'Millennium Bridge, London')
        self.assertEqual(source.page.call_args_list[-1].args[0], 'Millennium Bridge, London')
        before = source.page.call_count
        with self.assertRaisesRegex(ValueError, 'Missing source page'):
            discovery.resolved_page(source, 'Himeji Park', city_hint='Himeji')
        self.assertEqual(source.page.call_count, before + 1)
        source.page.side_effect = ValueError('Source has no unique Earth coordinate.')
        with self.assertRaisesRegex(ValueError, 'unique Earth coordinate'):
            discovery.resolved_page(source, 'Wrong Point', city_hint='London')
        self.assertEqual(source.page.call_count, before + 2)
        self.assertEqual(discovery.anchor_name(pages['Millennium Bridge, London'], 'Millennium Bridge',
                                               'The target overlooks Millennium Bridge.'), 'Millennium Bridge')

    def test_country_fetch_limits_claims_and_caches_result(self):
        source = discovery.WikimediaSource(self.budget())
        def response(host, params):
            if params['action'] == 'wbgetentities':
                self.assertNotIn('claims', params['props'].split('|'))
                return {'entities': {'Q100': {'labels': {'en': {'value': 'Example'}}}}}
            self.assertEqual(params['property'], 'P297')
            return {'claims': {}}
        with patch.object(source, 'request', side_effect=response) as request:
            source.country('Q100')
            source.country('Q100')
            self.assertEqual(request.call_count, 2)

    def test_excerpt_retains_distant_anchor_passage_with_bounded_model_input(self):
        candidate = {'anchors': [{'name': 'City'}, {'name': 'Local Park'}],
                     'evidence': {'article': {'text': 'City. ' + 'Source history. ' * 2000 + 'Next to Local Park.'}}}
        excerpts = discovery.evidence_excerpt(candidate)
        self.assertIn('Local Park', ' '.join(excerpts))
        self.assertLess(sum(map(len, excerpts)), 8500)
        candidate['anchors'][1]['name'] = 'Invented Area'
        with self.assertRaises(ValueError):
            discovery.evidence_excerpt(candidate)

    def test_evidence_units_keep_anchor_whole_across_chunk_boundary(self):
        candidate = {
            'anchors': [{'name': 'Local Park'}, {'name': 'River Walk'}],
            'evidence': {
                'article': {
                    'text': (
                        'A' * 494
                        + 'Local Park is beside the landmark. '
                        + 'B' * 520
                        + 'River Walk is visible nearby.'
                    )
                }
            },
        }

        units = discovery.evidence_units(candidate)

        self.assertTrue(any('Local Park' in unit['text'] for unit in units))
        self.assertTrue(any('River Walk' in unit['text'] for unit in units))
        anchor_units = [unit for unit in units if unit['id'].startswith('article-anchor-')]
        self.assertEqual(
            [(unit['anchor_name'], unit['clue_role']) for unit in anchor_units],
            [('Local Park', 'medium'), ('River Walk', 'easy')],
        )

    def test_only_map_key_is_used_and_failed_request_is_not_retried(self):
        budget = self.budget()
        with patch.dict(os.environ, {'GEMINI_API_KEY_DEV': 'dev-fixture', 'GEMINI_API_KEY': 'general-fixture'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'MAP_AI_API_KEY'):
                discovery.DiscoveryProvider.from_map_env(budget)
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        with patch.object(provider.clients[0].provider, '_request', side_effect=RuntimeError('map-fixture')) as request:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    provider.call_with_fallback(model_attr='generator_model', prompt='test', schema={})
            self.assertEqual(request.call_count, 1)
            self.assertNotIn('map-fixture', json.dumps(provider.requests))
        self.assertEqual(budget.finish('failed', self.root / 'report.json')['model_requests'], 1)

    def test_evidence_is_exact_and_unsupported_numbers_are_rejected(self):
        candidate, result = discovery.validate_selection(self.payload, [self.place])
        self.assertEqual(candidate['review_status'], 'pending')
        self.assertTrue(result['automated_pass'])
        for key, value in [('quote', 'A invented quotation that is not in the article at all.'),
                           ('text', 'A landmark built during the year 9999 with its original designer.')]:
            payload = deepcopy(self.payload)
            payload['facts']['hard'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                discovery.validate_selection(payload, [self.place])

    def test_passage_ids_copy_original_evidence_and_form_the_three_clues(self):
        units = discovery.evidence_units(self.place)
        payload = {'place_id': self.place['id'], 'selection_reason': self.payload['selection_reason'],
                   'facts': {level: {'text': fact['text'], 'source_ids': [unit['id'] for unit in units]}
                             for level, fact in self.place['facts'].items()}}
        candidate, result = discovery.validate_selection(payload, [self.place])
        self.assertEqual(result['clue_ladder']['hard'], payload['facts']['hard']['text'])
        self.assertEqual(candidate['facts']['hard']['supporting_quotes'], [unit['text'] for unit in units])
        payload['facts']['hard']['source_ids'] = ['invented-passage']
        with self.assertRaisesRegex(ValueError, 'passage reference'):
            discovery.validate_selection(payload, [self.place])

    def test_missing_anchor_citation_is_completed_only_for_an_anchored_clue(self):
        self.place['evidence']['article']['text'] = (
            self.place['facts']['hard']['text'] + ' ' +
            self.place['facts']['medium']['text'] + ' ' +
            'A separate source paragraph describes the exhibition. ' * 18 +
            self.place['facts']['easy']['text']
        )
        payload = deepcopy(self.payload)
        payload['facts']['easy'] = {
            'text': self.place['facts']['easy']['text'],
            'source_ids': ['article-0'],
        }
        units = {unit['id']: unit['text'] for unit in discovery.evidence_units(self.place)}
        self.assertNotIn('Heysel', units['article-0'])
        candidate, result = discovery.validate_selection(payload, [self.place])
        self.assertIn('Heysel', ' '.join(candidate['facts']['easy']['supporting_quotes']))
        self.assertTrue(result['automated_pass'])

        payload['facts']['easy']['text'] = 'Look near the northern part of the city.'
        with self.assertRaisesRegex(ValueError, 'quotation does not name its search area'):
            discovery.validate_selection(payload, [self.place])

    def test_source_quote_does_not_override_existing_answer_leak_checks(self):
        payload = deepcopy(self.payload)
        payload['clues']['hard']['text'] = 'The Atomium was built to celebrate this striking scientific idea.'
        with self.assertRaises(ValueError):
            discovery.validate_selection(payload, [self.place])

    def test_pending_candidate_cannot_be_used_by_runtime(self):
        candidate, _ = discovery.validate_selection(self.payload, [self.place])
        path = self.root / 'catalog.json'
        path.write_text(json.dumps({'version': 1, 'places': [candidate]}))
        with self.assertRaisesRegex(ValueError, 'source review'):
            controlled.load_catalog(path)

    def test_promotion_requires_exact_reviewed_content_and_preserves_catalogue(self):
        candidate, _ = discovery.validate_selection(self.payload, [self.place])
        report = {'status': 'needs_source_review', 'candidate': candidate, 'model_output': self.payload,
                  'resolved_candidates': [self.place]}
        report_path = self.root / 'report.json'
        report_path.write_text(json.dumps(report))
        catalog = self.root / 'catalog.json'
        existing = [p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG) if p['id'] != 'atomium']
        catalog.write_text(json.dumps({'version': 1, 'places': existing}))
        before = catalog.read_bytes()
        with self.assertRaises(ValueError):
            discovery.promote(report_path, catalog, 'wrong')
        self.assertEqual(catalog.read_bytes(), before)
        discovery.promote(report_path, catalog, discovery.digest(candidate))
        updated = controlled.load_catalog(catalog)
        self.assertEqual(updated[:-1], existing)
        self.assertEqual(updated[-1]['review_status'], 'source_reviewed')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            discovery.promote(report_path, catalog, discovery.digest(candidate))

    def test_tampered_evidence_cannot_be_promoted_with_old_candidate_hash(self):
        candidate, _ = discovery.validate_selection(self.payload, [self.place])
        report = {'status': 'needs_source_review', 'candidate': candidate, 'model_output': self.payload,
                  'resolved_candidates': [deepcopy(self.place)]}
        report['resolved_candidates'][0]['evidence']['article']['text'] = 'Unrelated content.'
        report_path = self.root / 'report.json'
        report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            discovery.promote(report_path, controlled.DEFAULT_CATALOG, discovery.digest(candidate))

    def test_history_is_read_only_and_blocks_published_dates(self):
        path = self.root / 'history.db'
        with sqlite3.connect(path) as conn:
            conn.executescript("CREATE TABLE daily_map_puzzles(id,puzzle_date,status);"
                               "CREATE TABLE daily_map_levels(puzzle_id,place_id);"
                               "CREATE TABLE map_place_pool(id,canonical_name,acceptable_aliases,place_type,lat,lng);"
                               "INSERT INTO daily_map_puzzles VALUES(1,'2026-09-09','published');"
                               "INSERT INTO daily_map_levels VALUES(1,1);"
                               "INSERT INTO map_place_pool VALUES(1,'Sample','Alias','castle',10,20);")
        conn.close()
        before = path.read_bytes()
        self.assertEqual(discovery.history(path, '2026-09-10')[0]['name'], 'Sample')
        with self.assertRaisesRegex(ValueError, 'already published'):
            discovery.history(path, '2026-09-09')
        self.assertEqual(path.read_bytes(), before)

    def source_fixture(self):
        source = Mock()
        source.budget.day = '2026-09-10'
        pages = {'Target': {'title': 'Target', 'entity': 'Q100', 'lat': 50, 'lng': 1, 'text': 'The Target is in City, beside Park.', 'url': 'https://en.wikipedia.org/?oldid=100'},
                 'City': {'title': 'City', 'entity': 'Q101', 'lat': 50.04, 'lng': 1, 'text': 'city', 'url': 'https://en.wikipedia.org/?oldid=101'},
                 'Park': {'title': 'Park', 'entity': 'Q102', 'lat': 50.01, 'lng': 1, 'text': 'park', 'url': 'https://en.wikipedia.org/?oldid=102'}}
        source.page.side_effect = lambda name: pages[name]
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value', 'datavalue': {'value': value}}}
        entity = {'lastrevid': 10, 'claims': {'P625': [claim({'latitude': 50, 'longitude': 1, 'globe': 'http://www.wikidata.org/entity/Q2'})],
                                            'P17': [claim({'id': 'Q200'})]}}
        country = {'labels': {'en': {'value': 'France'}}, 'claims': {'P297': [claim('FR')]}}
        source.entities.side_effect = lambda ids: {key: {'Q100': entity, 'Q200': country}[key] for key in ids}
        source.country.return_value = country
        proposal = {'title': 'Target', 'city_title': 'City', 'local_title': 'Park', 'place_type': 'castle', 'reason': 'A distinctive royal story.'}
        return source, entity, pages, proposal

    def test_resolved_coordinates_and_nested_geometry_are_source_derived(self):
        source, _, _, proposal = self.source_fixture()
        proposal['lat'] = -80
        candidate = discovery.resolve(proposal, source, [], [])
        self.assertEqual(candidate['lat'], 50)
        medium, easy = candidate['anchors']
        distance = discovery.daily_map_game.haversine_m(medium['lat'], medium['lng'], easy['lat'], easy['lng'])
        self.assertLess(distance + easy['radius_m'], medium['radius_m'])

    def test_invalid_map_routes_do_not_spend_country_source_requests(self):
        source, _, pages, proposal = self.source_fixture()
        pages['Park']['lat'] = pages['Target']['lat']
        pages['Park']['lng'] = pages['Target']['lng']
        with self.assertRaisesRegex(ValueError, 'Search area centres'):
            discovery.resolve(proposal, source, [], [])
        source.country.assert_not_called()

        source, _, pages, proposal = self.source_fixture()
        pages['Target']['text'] = 'The Target is in City, with a different nearby feature.'
        with self.assertRaisesRegex(ValueError, 'does not mention the supplied search area'):
            discovery.resolve(proposal, source, [], [])
        source.country.assert_not_called()

    def test_resolve_uses_area_batch_only_after_full_target_fetch(self):
        fixture, _, _, proposal = self.source_fixture()
        source = discovery.WikimediaSource(self.budget())
        with patch.object(source, 'page', side_effect=fixture.page.side_effect) as full_page, \
             patch.object(source, 'area_page', side_effect=fixture.page.side_effect) as area_page, \
             patch.object(source, 'prefetch_area_pages') as prefetch, \
             patch.object(source, 'entities', side_effect=fixture.entities.side_effect), \
             patch.object(source, 'country', return_value=fixture.country.return_value):
            candidate = discovery.resolve(proposal, source, [], [])
        self.assertEqual(candidate['canonical_name'], 'Target')
        full_page.assert_called_once_with('Target')
        prefetch.assert_called_once_with(['City', 'Park'])
        self.assertEqual([call.args[0] for call in area_page.call_args_list], ['City', 'Park'])

    def test_resolve_reports_which_source_article_failed(self):
        source, _, _, proposal = self.source_fixture()
        source.page.side_effect = lambda name: (_ for _ in ()).throw(ValueError('Missing source page.')) if name == 'Park' else {
            'Target': {'title': 'Target', 'entity': 'Q100', 'lat': 50, 'lng': 1, 'text': 'City and Park', 'url': 'x'},
            'City': {'title': 'City', 'entity': 'Q101', 'lat': 50.04, 'lng': 1, 'text': 'city', 'url': 'y'},
        }[name]
        with self.assertRaisesRegex(ValueError, 'Local feature article: Missing source page'):
            discovery.resolve(proposal, source, [], [])

    def test_coordinate_disagreement_duplicate_alias_and_recent_type_fail(self):
        source, entity, _, proposal = self.source_fixture()
        entity['claims']['P625'][0]['mainsnak']['datavalue']['value']['latitude'] = 0
        with self.assertRaisesRegex(ValueError, 'disagree'):
            discovery.resolve(proposal, source, [], [])
        source, _, _, proposal = self.source_fixture()
        for previous in [{'name': 'Other', 'aliases': 'Target', 'type': 'bridge', 'lat': 10, 'lng': 10, 'date': '2026-09-09'},
                         {'name': 'Other', 'aliases': '', 'type': 'castle', 'lat': 10, 'lng': 10, 'date': '2026-09-09'}]:
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                discovery.resolve(proposal, source, [previous], [])

    def test_full_discovery_records_two_calls_and_exports_review_without_publishing(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        self.place['proposal_reason'] = 'A memorable structure.'
        second = self.second_place()
        proposals = {'candidates': [{'title': f'Proposal {index}'} for index in range(discovery.PROPOSAL_COUNT)]}
        before = controlled.DEFAULT_CATALOG.read_bytes()
        with patch.object(discovery, 'history', return_value=[]), patch.object(discovery, 'resolve', side_effect=[self.place, second]), \
             patch.object(provider.clients[0].provider, '_request', side_effect=[proposals, self.payload]) as request:
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=controlled.DEFAULT_CATALOG,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock(), route_failure_lessons=[
                                            {'place': 'Himeji Castle',
                                             'failed_route_reason': 'Local feature article: Missing source page.'}])
        self.assertEqual(report['status'], 'needs_source_review')
        self.assertEqual(report['request_counts']['model_requests'], 2)
        self.assertTrue(all(region in request.call_args_list[0].args[1] for region in discovery.proposal_focus(budget)))
        self.assertEqual(len(report['rejections']), 0)
        self.assertEqual(len(report['resolved_candidates']), 2)
        self.assertEqual(request.call_args_list[0].args[2]['properties']['candidates']['minItems'], discovery.PROPOSAL_COUNT)
        self.assertIn('four landmarks from EACH', request.call_args_list[0].args[1])
        self.assertIn('recent_bad_map_routes', request.call_args_list[0].args[1])
        self.assertIn('Himeji Castle', request.call_args_list[0].args[1])
        self.assertIn('medium="Look in Brussels, Belgium, the city that hosted this landmark during Expo 58."',
                      request.call_args_list[1].args[1])
        self.assertFalse(report['production_modified'])
        self.assertFalse((self.root / 'unused.db').exists())
        self.assertEqual(controlled.DEFAULT_CATALOG.read_bytes(), before)
        self.assertIn('Supporting quotation:', Path(report['review_path']).read_text())
        self.assertNotIn('map-fixture', Path(report['report_path']).read_text())

    def test_discovery_can_choose_the_stronger_hook_from_a_second_resolved_place(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        second = self.second_place()
        selected = {
            'place_id': second['id'],
            'selection_reason': 'The source describes a recognisable event owned by this landmark.',
            'facts': {level: {'quote': fact['text'], 'text': fact['text']} for level, fact in second['facts'].items()},
            'clues': {level: {'text': fact['text'], 'fact_id': level} for level, fact in second['facts'].items()},
        }
        proposals = {'candidates': [{'title': f'Proposal {index}'} for index in range(discovery.PROPOSAL_COUNT)]}
        with patch.object(discovery, 'history', return_value=[]), \
             patch.object(discovery, 'resolve', side_effect=[self.place, second]) as resolve, \
             patch.object(provider.clients[0].provider, '_request', side_effect=[proposals, selected]) as request:
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=None,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock())
        self.assertEqual(report['status'], 'needs_source_review', report.get('error'))
        self.assertEqual(report['candidate']['id'], second['id'])
        self.assertEqual(len(report['resolved_candidates']), 2)
        self.assertEqual(resolve.call_count, 2)
        self.assertIn(self.place['id'], request.call_args_list[1].args[1])
        self.assertIn(second['id'], request.call_args_list[1].args[1])

    def test_source_budget_exhaustion_keeps_first_resolved_candidate(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        proposals = {'candidates': [{'title': f'Proposal {index}'} for index in range(discovery.PROPOSAL_COUNT)]}
        with patch.object(discovery, 'history', return_value=[]), \
             patch.object(discovery, 'resolve', side_effect=[self.place, ValueError('Source request budget exhausted.')]) as resolve, \
             patch.object(provider.clients[0].provider, '_request', side_effect=[proposals, self.payload]):
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=None,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock())
        self.assertEqual(report['status'], 'needs_source_review', report.get('error'))
        self.assertEqual(report['candidate']['id'], self.place['id'])
        self.assertEqual(len(report['resolved_candidates']), 1)
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(report['rejections'], [])
        self.assertEqual(report['budget_exhausted_at_title'], 'Proposal 1')

    def test_invalid_clue_ladder_gets_one_evidence_grounded_repair(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        invalid = deepcopy(self.payload)
        invalid['clues']['easy']['text'] = 'Look somewhere in Brussels.'
        with self.assertRaises(ValueError):
            discovery.validate_selection(invalid, [self.place])
        proposals = {'candidates': [{'title': f'Proposal {index}'} for index in range(discovery.PROPOSAL_COUNT)]}
        with patch.object(discovery, 'history', return_value=[]), \
             patch.object(discovery, 'resolve', side_effect=[self.place] + [ValueError('No second place')] * 11), \
             patch.object(provider.clients[0].provider, '_request', side_effect=[proposals, invalid, self.payload]) as request:
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=None,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock())
        self.assertEqual(report['status'], 'needs_source_review', report.get('error'))
        self.assertTrue(report['repair_attempted'])
        self.assertEqual(report['request_counts']['model_requests'], 3)
        self.assertEqual(request.call_count, 3)
        self.assertIn('VALIDATION FAILURE', request.call_args_list[2].args[1])
        self.assertEqual(report['candidate']['id'], self.place['id'])

    def test_source_budget_exhaustion_does_not_blacklist_unchecked_proposals(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        proposals = {'candidates': [{'title': f'Proposal {index}'} for index in range(discovery.PROPOSAL_COUNT)]}
        with patch.object(discovery, 'history', return_value=[]), \
             patch.object(discovery, 'resolve', side_effect=ValueError('Automatic map request budget exhausted.')) as resolve, \
             patch.object(provider.clients[0].provider, '_request', return_value=proposals):
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=None,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['rejections'], [])
        self.assertEqual(report['budget_exhausted_at_title'], 'Proposal 0')
        resolve.assert_called_once()

    def test_no_resolved_places_stops_before_second_model_call_and_reports_failure(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        with patch.object(discovery, 'history', return_value=[]), \
             patch.object(discovery, 'resolve', side_effect=ValueError('Missing source evidence.')), \
             patch.object(provider.clients[0].provider, '_request', return_value={'candidates': [{'title': f'Unknown {index}'} for index in range(discovery.PROPOSAL_COUNT)]}) as request:
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=controlled.DEFAULT_CATALOG,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['request_counts']['model_requests'], 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(report['rejections']), discovery.PROPOSAL_COUNT)
        self.assertIn('No fallback', report['error'])

    def test_twelve_proposals_can_reach_a_fresh_source_resolved_candidate_after_exclusions(self):
        budget = self.budget()
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = discovery.DiscoveryProvider.from_map_env(budget)
        self.place['proposal_reason'] = 'A memorable structure.'
        rejected = [f'Old place {index}' for index in range(discovery.PROPOSAL_COUNT - 1)]
        proposals = {'candidates': [{'title': name} for name in [*rejected, 'Fresh place']]}
        with patch.object(discovery, 'history', return_value=[]), patch.object(discovery, 'resolve', return_value=self.place) as resolve, \
             patch.object(provider.clients[0].provider, '_request', side_effect=[proposals, self.payload]):
            report = discovery.discover(source_db=self.root / 'unused.db', catalog=None,
                                        puzzle_date='2026-09-10', output_dir=self.root, budget=budget,
                                        provider=provider, sources=Mock(), excluded_names=rejected)
        self.assertEqual(report['status'], 'needs_source_review')
        self.assertEqual(len(report['rejections']), discovery.PROPOSAL_COUNT - 1)
        self.assertEqual(report['request_counts']['model_requests'], 2)
        resolve.assert_called_once()

    def test_reviewed_candidate_publishes_through_existing_game_and_hint_serializer(self):
        candidate, _ = discovery.validate_selection(self.payload, [self.place])
        candidate['review_status'] = 'source_reviewed'
        catalog = self.root / 'reviewed.json'
        catalog.write_text(json.dumps({'version': 1, 'places': [candidate]}))
        with patch.dict(os.environ, {'MAP_AI_API_KEY': 'map-fixture'}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            conn.commit()
            with patch.object(controlled.daily_map_game, 'map_learning_profile_hash', return_value='test-profile'), \
                 patch.object(provider, 'request_json', return_value=self.payload):
                result = controlled.generate_and_publish(conn, puzzle_date='2026-09-10', provider=provider, catalog=catalog)
            self.assertEqual(result['publish_result']['status'], 'published')
            conn.commit()
            row = dict(controlled.daily_map_game.level_rows(conn, '2026-09-10', -1)[0])
            for count in range(3):
                row['progress_revealed_hint_count'] = count
                payload = controlled.daily_map_game.serialize_level(row)
                self.assertEqual(len(payload['clues']), count + 1)
                self.assertEqual(len(payload['mapAnchors']), count)
                self.assertNotIn('result', payload)


if __name__ == '__main__':
    unittest.main()
