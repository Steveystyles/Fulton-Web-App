"""The replacement Map discovery must choose stories from sources before routes."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import map_story_pipeline as story
from tools import controlled_map_round as controlled


class StoryPipelineTests(unittest.TestCase):
    def test_review_shows_story_pivot_and_source_specific_citations(self):
        candidate = {'canonical_name': 'Glass Hall',
                     'sources': {'article': 'https://local-history.example/glass-hall',
                                 'city': 'https://en.wikipedia.org/wiki/Eastport',
                                 'local': 'https://en.wikipedia.org/wiki/Market_Park',
                                 'osm': 'https://www.openstreetmap.org/way/123'},
                     'facts': {level: {'supporting_quotes': [f'Sourced {level} passage.'],
                                      'source_ids': [source]}
                               for level, source in (('hard', 'article'), ('medium', 'city'),
                                                     ('easy', 'local'))},
                     'anchors': [{'name': 'Eastport'}, {'name': 'Market Park'}],
                     'coordinate_check': {'note': 'OSM and Wikidata coordinates cross-checked.'}}
        report = {'pipeline': 'story_first', 'status': 'needs_source_review',
                  'candidate': candidate, 'candidate_sha256': 'abc',
                  'result': {'selection_reason': 'A memorable public story.',
                             'clue_ladder': {level: f'{level} clue' for level in ('hard', 'medium', 'easy')}},
                  'story_pivot': {'original_story_passage': 'Generic location fact.',
                                  'new_story_passage': 'An inventive public exhibition.'},
                  'request_counts': {'model_requests': 3, 'source_requests': 12}}
        review = story.legacy.review_markdown(report)
        self.assertIn('Story changed during clue writing', review)
        self.assertIn('An inventive public exhibition.', review)
        self.assertIn('Evidence sources: city', review)
        self.assertIn('OpenStreetMap location data', review)
        self.assertNotIn('Wikipedia extracts: CC BY-SA 4.0', review)

    def test_non_wikipedia_place_uses_exact_osm_identity_and_public_page(self):
        geocoder = Mock()
        geocoder.search.return_value = [
            {'name': 'Glass Hall', 'wikidata': 'Q123', 'country_code': 'GB',
             'country_name': 'United Kingdom', 'website': 'https://glass.example/story',
             'lat': 51.5, 'lng': -0.12, 'url': 'https://www.openstreetmap.org/way/123'},
            {'name': 'Glass Hall East', 'wikidata': 'Q456', 'country_code': 'GB',
             'country_name': 'United Kingdom', 'website': 'https://east.example/',
             'lat': 51.6, 'lng': -0.12, 'url': 'https://www.openstreetmap.org/way/456'},
        ]
        external = {'text': 'Glass Hall hosted the first public solar railway demonstration. ' * 12,
                    'url': 'https://glass.example/story', 'source_name': 'glass.example',
                    'source_key': 'external'}
        with patch.object(story, 'public_page', return_value=external) as fetch:
            page, evidence = story.non_wikipedia_target('Glass Hall', Mock(), geocoder)
        self.assertEqual(page['entity'], 'Q123')
        self.assertEqual(page['source_kind'], 'osm_public_page')
        self.assertEqual(evidence, external)
        fetch.assert_called_once_with(unittest.mock.ANY, 'https://glass.example/story', 'Glass Hall')

    def test_non_wikipedia_place_can_use_any_checked_public_story_site(self):
        geocoder = Mock()
        geocoder.search.return_value = [
            {'name': 'Glass Hall', 'wikidata': 'Q123', 'country_code': 'GB',
             'country_name': 'United Kingdom', 'website': '', 'lat': 51.5, 'lng': -0.12,
             'url': 'https://www.openstreetmap.org/way/123'}]
        external = {'text': 'Glass Hall hosted a railway demonstration. ' * 15,
                    'url': 'https://local-history.example/glass-hall',
                    'source_name': 'local-history.example', 'source_key': 'external'}
        with patch.object(story, 'public_page', return_value=external) as fetch:
            page, evidence = story.non_wikipedia_target(
                'Glass Hall', Mock(), geocoder, 'https://local-history.example/glass-hall')
        self.assertEqual(page['url'], evidence['url'])
        fetch.assert_called_once_with(unittest.mock.ANY, external['url'], 'Glass Hall')

    def test_wikidata_identity_uses_public_story_without_geocoding(self):
        source = Mock()
        source.entities.return_value = {'Q123': {
            'lastrevid': 44, 'labels': {'en': {'value': 'Glass Hall'}},
            'claims': {'P625': [{'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                        'datavalue': {'value': {'latitude': 51.5, 'longitude': -0.12,
                                               'globe': 'http://www.wikidata.org/entity/Q2'}}}}],
                       'P17': [{'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                                 'datavalue': {'value': {'id': 'Q145'}}}}]}}}
        external = {'text': 'Glass Hall hosted the first public solar railway demonstration. ' * 12,
                    'url': 'https://local-history.example/glass-hall',
                    'source_name': 'local-history.example', 'source_key': 'external'}
        geocoder = Mock()
        with patch.object(story, 'public_page', return_value=external):
            page, evidence = story.non_wikipedia_target(
                'Glass Hall', source, geocoder, external['url'], 'Q123')
        self.assertEqual(page['source_kind'], 'wikidata_public_page')
        self.assertEqual((page['lat'], page['lng']), (51.5, -0.12))
        self.assertEqual(evidence, external)
        geocoder.search.assert_not_called()

    def test_wikidata_identity_rejects_different_place_name(self):
        source = Mock()
        source.entities.return_value = {'Q123': {'labels': {'en': {'value': 'Another Hall'}}}}
        with self.assertRaisesRegex(ValueError, 'does not have the proposed place name'):
            story.non_wikipedia_target('Glass Hall', source, None,
                                       'https://local-history.example/glass-hall', 'Q123')

    def test_source_targets_falls_back_when_wikipedia_has_no_article(self):
        source = Mock()
        source.budget.day = '2026-10-15'
        geocoder = Mock()
        external = {'text': 'Glass Hall hosted the first public solar railway demonstration. ' * 12,
                    'url': 'https://glass.example/story', 'source_name': 'glass.example',
                    'source_key': 'external'}
        page = {'title': 'Glass Hall', 'entity': 'Q123', 'lat': 51.5, 'lng': -0.12,
                'text': external['text'], 'url': external['url'],
                'source_kind': 'osm_public_page', 'osm_url': 'https://www.openstreetmap.org/way/123'}
        report = {'rejections': []}
        with patch.object(story.legacy, 'resolved_page', side_effect=ValueError('Missing source page.')), \
             patch.object(story, 'non_wikipedia_target', return_value=(page, external)) as fallback, \
             patch.object(story, 'nearby_options', return_value=[]):
            targets = story.source_targets([{'title': 'Glass Hall', 'place_type': 'museum'}],
                                           source, [], [], [], report, geocoder=geocoder)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]['official'], external)
        self.assertEqual(targets[0]['passages'][0]['source'], 'glass.example')
        fallback.assert_called_once_with('Glass Hall', source, geocoder, '', '')
        source.entities.assert_not_called()

    def test_non_wikipedia_route_keeps_osm_provenance(self):
        source = Mock()
        target = {'page': {'title': 'Glass Hall', 'source_kind': 'osm_public_page',
                           'osm_url': 'https://www.openstreetmap.org/way/123'}}
        candidate = {'sources': {}, 'coordinate_check': {}}
        with patch.object(story.legacy, 'resolve', return_value=candidate) as resolve:
            checked, _ = story.resolve_route({'title': 'Glass Hall', 'local_title': 'Market Park'},
                                             target, source, [], [])
        self.assertIsInstance(resolve.call_args.args[1], story._TargetPageSource)
        self.assertEqual(checked['sources']['osm'], 'https://www.openstreetmap.org/way/123')

    def test_non_wikipedia_route_passes_real_geometry_and_anchor_checks(self):
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                                                  'datavalue': {'value': value}}}
        page = {'title': 'Glass Hall', 'entity': 'Q100', 'lat': 50, 'lng': 1,
                'text': 'The Glass Hall hosted an inventive public exhibition. ' * 20,
                'url': 'https://local-history.example/glass-hall',
                'source_kind': 'osm_public_page',
                'osm_url': 'https://www.openstreetmap.org/way/123'}
        areas = {'City': {'title': 'City', 'entity': 'Q101', 'lat': 50.04, 'lng': 1,
                          'text': 'City is a public settlement with a documented civic centre.',
                          'url': 'https://example.org/city'},
                 'Park': {'title': 'Park', 'entity': 'Q102', 'lat': 50.01, 'lng': 1,
                          'text': 'Park is a public green space beside the old exhibition grounds.',
                          'url': 'https://example.org/park'}}
        entity = {'lastrevid': 10, 'labels': {'en': {'value': 'Glass Hall'}},
                  'claims': {'P625': [claim({'latitude': 50, 'longitude': 1,
                                            'globe': 'http://www.wikidata.org/entity/Q2'})],
                             'P17': [claim({'id': 'Q200'})]}}
        country = {'labels': {'en': {'value': 'France'}},
                   'claims': {'P297': [claim('FR')]}}
        source = Mock()
        source.budget.day = '2026-10-15'
        source.area_page.side_effect = lambda name: areas[name]
        source.entities.return_value = {'Q100': entity}
        source.country.return_value = country
        route = {'title': 'Glass Hall', 'city_title': 'City', 'local_title': 'Park',
                 'place_type': 'museum', 'reason': 'A distinctive public demonstration.'}
        candidate, repair = story.resolve_route(route, {'page': page}, source, [], [])
        self.assertIsNone(repair)
        self.assertEqual(candidate['canonical_name'], 'Glass Hall')
        self.assertEqual(candidate['sources']['article'], page['url'])
        self.assertEqual(candidate['sources']['osm'], page['osm_url'])
        self.assertEqual(candidate['coordinate_check']['distance_m'], 0)
        self.assertIn('city-anchor-0', [unit['id'] for unit in story.legacy.evidence_units(candidate)])
        self.assertIn('local-anchor-1', [unit['id'] for unit in story.legacy.evidence_units(candidate)])
        selection = {'place_id': candidate['id'], 'selection_reason': 'A public exhibition story.',
                     'facts': {
                         'hard': {'text': 'This hall hosted an inventive public exhibition.',
                                  'source_ids': ['article-0']},
                         'medium': {'text': 'Look in City, France, for the exhibition hall.',
                                    'source_ids': ['city-anchor-0']},
                         'easy': {'text': 'In southern City, look near Park for the hall.',
                                  'source_ids': ['local-anchor-1']}}}
        with patch.object(story.controlled, 'load_catalog'), \
             patch.object(story.controlled, 'validate_result', return_value={'automated_pass': True}):
            checked, _ = story.legacy.validate_selection(selection, [candidate])
        self.assertEqual(checked['facts']['medium']['source_ids'], ['city'])
        self.assertEqual(checked['facts']['easy']['source_ids'], ['local'])
        wikidata_page = {**page, 'source_kind': 'wikidata_public_page'}
        wikidata_candidate, _ = story.resolve_route(route, {'page': wikidata_page}, source, [], [])
        self.assertNotIn('osm', wikidata_candidate['sources'])
        self.assertIn('Wikidata coordinates used', wikidata_candidate['coordinate_check']['note'])

    def test_external_story_route_does_not_require_navigation_names_in_story_page(self):
        passage = ('Glass Hall hosted the first public demonstration of solar rail '
                   'transport after its designers developed a novel roof.')
        source = {'text': passage, 'source_name': 'local-history.example'}
        target = {'title': 'Glass Hall', 'place_type': 'museum',
                  'page': {'text': passage, 'source_kind': 'wikidata_public_page'},
                  'official': source,
                  'passages': [{'id': 'p0', 'text': passage, 'role': 'story',
                                'source': source['source_name']}]}
        ranked = {'ranked': [{'title': 'Glass Hall', 'passage_id': 'p0',
                              'hook': 'The first public demonstration of solar rail transport '
                                      'followed a novel roof design.',
                              'city_title': 'Eastport', 'local_title': 'Market Park'}]}
        routes = story.ranked_routes(ranked, [target])
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]['city_title'], 'Eastport')

    def test_full_source_first_flow_saves_review_without_publication(self):
        place = deepcopy(next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG)
                              if p['id'] == 'atomium'))
        article_text = ' '.join(fact['text'] for fact in place['facts'].values())
        page = {'title': 'Atomium', 'text': article_text, 'entity': 'Q1', 'lat': place['lat'],
                'lng': place['lng']}
        target = {'title': 'Atomium', 'place_type': place['place_type'], 'page': page,
                  'passages': [{'id': 'p0', 'text': article_text, 'role': 'story', 'source': 'Wikipedia'}],
                  'nearby_options': [{'title': 'Heysel', 'distance_m': 700}]}
        place['sources'] = {'article': place['sources']['history'],
                            'city': place['sources']['district'], 'local': place['sources']['access']}
        place['evidence'] = {'article': {'text': article_text}}
        place['proposal_reason'] = place['facts']['hard']['text']
        place['retrieved_on'] = story.legacy.date.today().isoformat()
        place['city_sector'] = 'northern'
        clue_payload = {'place_id': place['id'],
                        'selection_reason': 'The iron-crystal design gives this landmark a memorable identity.',
                        'facts': {level: {'text': fact['text'], 'source_ids': ['article-0']}
                                  for level, fact in place['facts'].items()}}
        provider = Mock()
        provider.clients = [SimpleNamespace(config=SimpleNamespace(gemini_api_key='test-key'))]
        provider.requests = []
        provider.call_with_fallback.side_effect = [
            {'targets': [{'title': f'Target {i}', 'place_type': 'museum'} for i in range(12)]},
            {'ranked': [{'title': 'Atomium', 'passage_id': 'p0', 'hook': place['proposal_reason'],
                         'city_title': 'Brussels', 'local_title': 'Heysel'}]},
            clue_payload,
        ]
        budget = Mock(day='2026-10-15', budget_day='2026-10-15', attempt_number=1)
        budget.finish.return_value = {'model_requests': 3, 'source_requests': 1}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(story.legacy, 'history', return_value=[]), \
             patch.object(story, 'source_targets', return_value=[target]), \
             patch.object(story.legacy, 'resolve', return_value=place):
            report = story.discover(source_db=Path(directory) / 'db', catalog=None,
                                    puzzle_date='2026-10-17', output_dir=Path(directory),
                                    budget=budget, provider=provider, sources=Mock(),
                                    editorial_feedback=[{'rejected_hook': 'A generic old hook'}],
                                    route_failure_lessons=[{'failed_route_reason': 'An unplayable old park'}],
                                    failure_lessons=[{'failure_reason': 'A weak story was rejected'}])
            self.assertEqual(report['status'], 'needs_source_review', report.get('error'))
            self.assertFalse(report['production_modified'])
            self.assertTrue(Path(report['report_path']).exists())
            self.assertEqual(provider.call_with_fallback.call_count, 3)
            ranking_prompt = provider.call_with_fallback.call_args_list[1].kwargs['prompt']
            self.assertIn('A generic old hook', ranking_prompt)
            self.assertIn('An unplayable old park', ranking_prompt)
            self.assertIn('A weak story was rejected', ranking_prompt)
            self.assertIn('when rejection_kind is clue_ladder', ranking_prompt)

    def test_story_evidence_is_bounded_before_model_call(self):
        provider = Mock()
        provider.clients = [SimpleNamespace(config=SimpleNamespace(gemini_api_key='test-key'))]
        provider.requests = []
        provider.call_with_fallback.side_effect = [
            {'targets': [{'title': f'Target {i}', 'place_type': 'museum'} for i in range(12)]},
            {'ranked': [{'title': 'Unknown', 'passage_id': 'p0', 'hook': 'No useful evidence here.',
                         'city_title': 'Nowhere', 'local_title': 'Nothing'}]},
        ]
        targets = [{'title': f'Target {i}', 'place_type': 'museum',
                    'page': {'title': f'Target {i}', 'text': 'Source text.'},
                    'passages': [{'id': f'p{j}', 'role': 'story', 'source': 'Wikipedia',
                                  'text': 'An interesting public story. ' * 50} for j in range(5)],
                    'nearby_options': []} for i in range(12)]
        budget = Mock(day='2026-10-15', budget_day='2026-10-15', attempt_number=1)
        budget.finish.return_value = {'model_requests': 2, 'source_requests': 0}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(story.legacy, 'history', return_value=[]), \
             patch.object(story, 'source_targets', return_value=targets):
            report = story.discover(source_db=Path(directory) / 'db', catalog=None,
                                    puzzle_date='2026-10-17', output_dir=Path(directory),
                                    budget=budget, provider=provider, sources=Mock())
        self.assertLess(report['story_target_count'], 12)
        self.assertLessEqual(len(provider.call_with_fallback.call_args_list[1].kwargs['prompt']), 36000)

    def test_nearby_options_are_from_api_and_named_in_target_article(self):
        source = Mock()
        source.request.return_value = {'query': {'geosearch': [
            {'title': 'Glass Hall', 'dist': 0},
            {'title': 'Market Park', 'dist': 730},
            {'title': 'Unknown Museum', 'dist': 800},
            {'title': 'Far Garden', 'dist': 4900},
        ]}}
        page = {'title': 'Glass Hall', 'lat': 51.0, 'lng': 0.1,
                'text': 'The Glass Hall is near Market Park in Eastport.'}
        self.assertEqual(story.nearby_options(page, source), [{'title': 'Market Park', 'distance_m': 730}])
        self.assertEqual(source.request.call_args.args[0], 'en.wikipedia.org')

    def test_public_url_accepts_any_public_https_domain_but_not_internal_hosts(self):
        public_dns = [(story.socket.AF_INET, story.socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        with patch.object(story.socket, 'getaddrinfo', return_value=public_dns):
            self.assertEqual(story.checked_public_url('https://example.org/story?id=1'),
                             ('example.org', '/story?id=1', '93.184.216.34'))
        private_dns = [(story.socket.AF_INET, story.socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch.object(story.socket, 'getaddrinfo', return_value=private_dns):
            with self.assertRaisesRegex(ValueError, 'non-public'):
                story.checked_public_url('https://example.org/story')
        for url in ('http://example.org/story', 'https://user:pass@example.org/story',
                    'https://example.org:8443/story', 'https://127.0.0.1/story'):
            with self.assertRaises(ValueError):
                story.checked_public_url(url)

    def test_public_page_checks_place_identity_and_bounds_redirects(self):
        source = Mock()
        response = Mock(status=200)
        response.getheader.return_value = 'text/html; charset=utf-8'
        response.read.return_value = (b'<nav>Menu</nav><main><h1>Glass Hall</h1><p>' +
                                      b'The first public demonstration of a solar railway occurred here. ' * 12 +
                                      b'</p></main>')
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(story, 'checked_public_url', return_value=('example.org', '/story', '93.184.216.34')), \
             patch.object(story, '_PinnedHTTPSConnection', return_value=connection) as factory:
            page = story.public_page(source, 'https://example.org/story', 'Glass Hall')
        factory.assert_called_once_with('example.org', '93.184.216.34')
        self.assertEqual(page['source_key'], 'external')
        self.assertIn('solar railway', page['text'])
        self.assertNotIn('Menu', page['text'])
        response.status = 302
        response.getheader.side_effect = lambda name: (
            'http://127.0.0.1/internal' if name == 'Location' else 'text/html')
        with patch.object(story, 'checked_public_url', side_effect=[
                ('example.org', '/story', '93.184.216.34'),
                ValueError('Public sources require a normal HTTPS host.')]), \
             patch.object(story, '_PinnedHTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'normal HTTPS'):
                story.public_page(source, 'https://example.org/story', 'Glass Hall')
        response.status = 200
        response.getheader.side_effect = None

    def test_public_page_rechecks_a_valid_redirect_destination(self):
        source = Mock()
        redirect = Mock(status=301)
        redirect.getheader.return_value = 'https://another.example/glass-hall-story'
        final = Mock(status=200)
        final.getheader.return_value = 'text/html'
        final.read.return_value = (b'<main>Glass Hall hosted the first public demonstration '
                                   b'of a solar railway. ' * 20 + b'</main>')
        first_connection = Mock()
        first_connection.getresponse.return_value = redirect
        second_connection = Mock()
        second_connection.getresponse.return_value = final
        with patch.object(story, 'checked_public_url', side_effect=[
                ('example.org', '/story', '93.184.216.34'),
                ('another.example', '/glass-hall-story', '93.184.216.35')]) as checked, \
             patch.object(story, '_PinnedHTTPSConnection', side_effect=[
                 first_connection, second_connection]) as factory:
            page = story.public_page(source, 'https://example.org/story', 'Glass Hall')
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(page['url'], 'https://another.example/glass-hall-story')
        self.assertEqual(source.budget.spend.call_count, 2)

    def test_linked_public_urls_uses_official_record_and_relevant_external_links(self):
        source = Mock()
        source.request.return_value = {'query': {'pages': [{'extlinks': [
            {'url': 'https://museum.example/glass-hall-story'},
            {'url': 'https://other.example/unrelated-page'},
        ]}]}}
        entity = {'claims': {'P856': [{'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                  'datavalue': {'value': 'https://museum.example/'}}}]}}
        urls = story.linked_public_urls({'title': 'Glass Hall'}, entity, source)
        self.assertEqual(urls, ['https://museum.example/', 'https://museum.example/glass-hall-story'])
        self.assertEqual(source.request.call_args.args[0], 'en.wikipedia.org')

    def test_route_repair_only_substitutes_public_nearby_article(self):
        route = {'title': 'Glass Hall', 'city_title': 'Eastport', 'local_title': 'Imaginary Park'}
        target = {'nearby_options': [{'title': 'Market Park', 'distance_m': 730}]}
        with patch.object(story.legacy, 'resolve', side_effect=[ValueError('Local feature article: Missing source page.'),
                                                                {'id': 'q1'}]) as resolve:
            candidate, replacement = story.resolve_route(route, target, Mock(), [], [])
        self.assertEqual(candidate['id'], 'q1')
        self.assertEqual(replacement, 'Market Park')
        self.assertEqual(resolve.call_args_list[1].args[0]['city_title'], 'Eastport')
        self.assertEqual(resolve.call_args_list[1].args[0]['local_title'], 'Market Park')
        with patch.object(story.legacy, 'resolve', side_effect=ValueError('City article: Missing source page.')) as resolve:
            with self.assertRaisesRegex(ValueError, 'City article'):
                story.resolve_route(route, target, Mock(), [], [])
        resolve.assert_called_once()

    def test_guidance_fallback_uses_only_checked_anchors_not_an_address(self):
        payload = {'facts': {'hard': {'text': 'A sourced story.'},
                             'medium': {'text': 'At 400 Broad Street.'},
                             'easy': {'text': 'Go to 400 Broad Street.'}}}
        candidate = {'anchors': [{'name': 'Seattle'}, {'name': 'Lower Queen Anne'}],
                     'city_sector': 'northern', 'country_name': 'United States'}
        fixed = story.guidance_fallback(payload, candidate)
        self.assertEqual(fixed['facts']['hard'], payload['facts']['hard'])
        self.assertIn('Seattle, United States', fixed['facts']['medium']['text'])
        self.assertIn('Lower Queen Anne', fixed['facts']['easy']['text'])
        self.assertNotIn('400', str(fixed))
        self.assertIn('400', str(payload))

    def test_hard_story_pivot_requires_a_cited_target_passage(self):
        article = ('The Glass Hall in Eastport beside Market Park hosted the first public '
                   'demonstration of solar rail transport, after its designers sketched '
                   'a novel glass roof for the exhibition. ') * 5
        candidate = {'canonical_name': 'Glass Hall', 'proposal_reason': 'A generic location fact.',
                     'evidence': {'article': {'text': article}},
                     'anchors': [{'name': 'Eastport'}, {'name': 'Market Park'}]}
        hard = ('This hall hosted the first public demonstration of solar rail transport '
                'beneath a novel glass roof.')
        payload = {'facts': {'hard': {'text': hard, 'source_ids': ['article-0']}}}
        quote = story.checked_hard_story_pivot(payload, candidate)
        self.assertIn('solar rail transport', quote)
        self.assertIsNone(story.checked_hard_story_pivot(
            {'facts': {'hard': {'text': hard, 'source_ids': ['article-anchor-0']}}}, candidate))
        self.assertIsNone(story.checked_hard_story_pivot(
            {'facts': {'hard': {'text': 'An unrelated claim about a royal wedding.',
                                'source_ids': ['article-0']}}}, candidate))

    def test_official_hook_can_support_hard_clue_without_wikipedia_copy(self):
        place = next(p for p in controlled.load_catalog(controlled.DEFAULT_CATALOG) if p['id'] == 'atomium').copy()
        hard = place['facts']['hard']['text']
        medium = place['facts']['medium']['text']
        easy = place['facts']['easy']['text']
        place['evidence'] = {'article': {'text': medium + ' ' + easy},
                             'official': {'text': hard, 'hook_passage': hard}}
        place['sources'] = {'article': place['sources']['history'],
                            'city': place['sources']['district'],
                            'local': place['sources']['access'],
                            'unesco': 'https://whc.unesco.org/en/list/252/'}
        place['proposal_reason'] = hard
        place['retrieved_on'] = story.legacy.date.today().isoformat()
        payload = {'place_id': place['id'], 'selection_reason': 'The atomic design is a memorable place-owned story.',
                   'facts': {'hard': {'text': hard, 'source_ids': ['official-hook']},
                             'medium': {'text': medium, 'quote': medium},
                             'easy': {'text': easy, 'quote': easy}}}
        self.assertIn('official-hook', [unit['id'] for unit in story.legacy.evidence_units(place)])
        candidate, result = story.legacy.validate_selection(payload, [place])
        self.assertTrue(result['automated_pass'])
        self.assertEqual(candidate['facts']['hard']['source_ids'], ['unesco'])
        place['sources'].pop('unesco')
        place['sources']['historic_england'] = 'https://historicengland.org.uk/listing/the-list/list-entry/1291494'
        place['evidence']['official']['source_key'] = 'historic_england'
        candidate, result = story.legacy.validate_selection(payload, [place])
        self.assertTrue(result['automated_pass'])
        self.assertEqual(candidate['facts']['hard']['source_ids'], ['historic_england'])
        place['sources'].pop('historic_england')
        place['sources']['external'] = 'https://example.org/atomium-story'
        place['evidence']['official']['source_key'] = 'external'
        candidate, result = story.legacy.validate_selection(payload, [place])
        self.assertTrue(result['automated_pass'])
        self.assertEqual(candidate['facts']['hard']['source_ids'], ['external'])
        with self.assertRaisesRegex(ValueError, 'unrelated passage'):
            story.legacy.validate_proposal_hook_alignment(
                {'facts': {'hard': {'text': hard, 'source_ids': ['article-0']}}}, place)

    def test_unesco_identity_requires_direct_wikidata_identifier(self):
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                    'datavalue': {'value': value}}}
        self.assertEqual(story.unesco_id({'claims': {'P757': [claim('252')]}}), '252')
        self.assertIsNone(story.unesco_id({'claims': {'P757': [claim('https://other.example/')]}}))
        self.assertIsNone(story.unesco_id({'claims': {}}))

    def test_historic_england_identity_requires_direct_wikidata_identifier(self):
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                    'datavalue': {'value': value}}}
        self.assertEqual(story.historic_england_id({'claims': {'P1216': [claim('1291494')]}}), '1291494')
        self.assertIsNone(story.historic_england_id({'claims': {'P1216': [claim('https://example.org/')]}}))
        self.assertIsNone(story.historic_england_id({'claims': {}}))

    def test_unesco_fetch_is_fixed_host_and_bounded_english_section(self):
        source = Mock()
        response = Mock(status=200)
        response.read.return_value = (b'<nav>Ignore navigation</nav><h1>Example</h1>'
                                      b'<h2>Outstanding Universal Value</h2><p>' +
                                      b'A distinctive cultural invention was demonstrated here. ' * 9 +
                                      b'</p><h2>Links</h2><p>Ignore footer links</p>')
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(story.http.client, 'HTTPSConnection', return_value=connection) as factory:
            page = story.unesco_page(source, '252')
        factory.assert_called_once_with('whc.unesco.org', timeout=20)
        self.assertIn('distinctive cultural invention', page['text'])
        self.assertNotIn('Ignore footer', page['text'])
        self.assertEqual(page['url'], 'https://whc.unesco.org/en/list/252/')
        source.budget.spend.assert_called_once_with('source')

    def test_historic_england_fetch_is_fixed_host_and_rejects_wrong_entry(self):
        source = Mock()
        response = Mock(status=200)
        response.read.return_value = (
            b'<nav>Ignore navigation</nav><h1>Example Abbey</h1>'
            b'<h2>Official list entry</h2><p>List Entry Number: 1291494</p>'
            b'<h3>Details</h3><p>A remarkable public ceremony was held in this abbey. ' * 8 +
            b'</p><h3>Legacy</h3><p>Ignore legacy material.</p>')
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(story.http.client, 'HTTPSConnection', return_value=connection) as factory:
            page = story.historic_england_page(source, '1291494')
        factory.assert_called_once_with('historicengland.org.uk', timeout=20)
        self.assertIn('remarkable public ceremony', page['text'])
        self.assertNotIn('Ignore legacy', page['text'])
        self.assertEqual(page['source_key'], 'historic_england')
        source.budget.spend.assert_called_once_with('source')
        with patch.object(story, 'official_html', return_value=(
                'Official list entry List Entry Number: 1000000 Details ' + 'A history. ' * 50)):
            with self.assertRaisesRegex(ValueError, 'does not identify'):
                story.historic_england_page(source, '1291494')

    def test_passages_are_bounded_and_include_story_beyond_introduction(self):
        text = 'A landmark in Example City. ' * 80
        text += 'A public experiment created a remarkable new transport system here. ' * 8
        items = story.passages({'text': text})
        self.assertLessEqual(len(items), 5)
        self.assertTrue(any('experiment' in item['text'] and item['role'] == 'story' for item in items))

    def test_ranked_route_rejects_invented_hook_or_anchor(self):
        article = ('The Glass Hall stands in Eastport beside Market Park. '
                   'It hosted the first public demonstration of a solar railway.')
        targets = [{'title': 'Glass Hall', 'place_type': 'museum', 'page': {'text': article},
                    'passages': [{'id': 'p0', 'text': article, 'role': 'story'}]}]
        item = {'title': 'Glass Hall', 'passage_id': 'p0',
                'hook': 'It hosted the first public demonstration of a solar railway.',
                'city_title': 'Eastport', 'local_title': 'Market Park'}
        self.assertEqual(len(story.ranked_routes({'ranked': [item]}, targets)), 1)
        self.assertEqual(story.ranked_routes({'ranked': [{**item, 'local_title': 'Fake Park'}]}, targets), [])
        self.assertEqual(story.ranked_routes({'ranked': [{**item, 'passage_id': 'fake'}]}, targets), [])
        self.assertEqual(story.ranked_routes({'ranked': [{**item, 'hook': 'An unrelated miraculous rescue happened here.'}]}, targets), [])
        targets[0]['passages'][0]['role'] = 'context'
        self.assertEqual(story.ranked_routes({'ranked': [item]}, targets), [])

    def test_official_only_story_is_eligible_when_direct_entry_matches(self):
        article = 'The Glass Hall stands in Eastport beside Market Park. '
        official_text = ('The public hall hosted the first demonstration of a solar railway, '
                         'bringing hundreds of visitors into the building.')
        target = {'title': 'Glass Hall', 'place_type': 'museum', 'page': {'text': article},
                  'official': {'text': official_text, 'source_name': 'Historic England'},
                  'passages': [{'id': 'op2', 'text': official_text, 'role': 'story',
                                'source': 'Historic England'}]}
        item = {'title': 'Glass Hall', 'passage_id': 'op2',
                'hook': 'The first public demonstration of a solar railway was hosted here.',
                'city_title': 'Eastport', 'local_title': 'Market Park'}
        self.assertEqual(len(story.ranked_routes({'ranked': [item]}, [target])), 1)
        target['official']['text'] = 'An unrelated official listing.'
        self.assertEqual(story.ranked_routes({'ranked': [item]}, [target]), [])

    def test_target_lookup_does_not_request_city_or_local_articles(self):
        source = Mock()
        source.budget.day = '2026-10-15'
        source.page.return_value = {'title': 'Glass Hall', 'entity': 'Q1', 'lat': 51, 'lng': 0,
                                    'text': 'The Glass Hall is in Eastport. ' * 30}
        source.entities.return_value = {'Q1': {'claims': {}}}
        report = {'rejections': []}
        targets = story.source_targets([{'title': 'Glass Hall', 'place_type': 'museum'}], source,
                                       [], [], [], report)
        self.assertEqual(len(targets), 1)
        source.page.assert_called_once_with('Glass Hall')
        source.country.assert_not_called()

    def test_target_lookup_adds_direct_historic_england_story_evidence(self):
        source = Mock()
        source.budget.day = '2026-10-15'
        source.page.return_value = {
            'title': 'Glass Hall', 'entity': 'Q1', 'lat': 51, 'lng': 0,
            'text': ('The Glass Hall is in Eastport beside Market Park. ' * 12) +
                    ('It hosted the first public demonstration of a solar railway. ' * 12),
        }
        source.request.return_value = {'query': {'geosearch': []}}
        source.entities.return_value = {'Q1': {'claims': {'P1216': [{
            'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                'datavalue': {'value': '1291494'}}}]}}}
        official = {'text': ('The entry records the public demonstration of a solar railway. ' * 24),
                    'url': 'https://historicengland.org.uk/listing/the-list/list-entry/1291494',
                    'source_key': 'historic_england', 'source_name': 'Historic England'}
        with patch.object(story, 'historic_england_page', return_value=official) as fetch:
            targets = story.source_targets([{'title': 'Glass Hall', 'place_type': 'museum'}],
                                           source, [], [], [], {'rejections': []})
        fetch.assert_called_once_with(source, '1291494')
        self.assertEqual(targets[0]['official']['source_key'], 'historic_england')
        self.assertTrue(any(item['source'] == 'Historic England' for item in targets[0]['passages']))

    def test_target_lookup_falls_back_to_second_official_source(self):
        source = Mock()
        source.budget.day = '2026-10-15'
        source.page.return_value = {
            'title': 'Glass Hall', 'entity': 'Q1', 'lat': 51, 'lng': 0,
            'text': ('The Glass Hall is in Eastport beside Market Park. ' * 12) +
                    ('It hosted the first public demonstration of a solar railway. ' * 12),
        }
        source.request.return_value = {'query': {'geosearch': []}}
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                    'datavalue': {'value': value}}}
        source.entities.return_value = {'Q1': {'claims': {
            'P757': [claim('252')], 'P1216': [claim('1291494')]}}}
        official = {'text': ('The entry records the public demonstration of a solar railway. ' * 24),
                    'url': 'https://historicengland.org.uk/listing/the-list/list-entry/1291494',
                    'source_key': 'historic_england', 'source_name': 'Historic England'}
        report = {'rejections': []}
        with patch.object(story, 'unesco_page', side_effect=RuntimeError('HTTP 503')) as unesco, \
             patch.object(story, 'historic_england_page', return_value=official) as historic:
            targets = story.source_targets([{'title': 'Glass Hall', 'place_type': 'museum'}],
                                           source, [], [], [], report)
        unesco.assert_called_once_with(source, '252')
        historic.assert_called_once_with(source, '1291494')
        self.assertEqual(targets[0]['official']['source_key'], 'historic_england')
        self.assertEqual(len(report['source_warnings']), 1)

    def test_target_lookup_uses_any_domain_linked_page_when_no_fixed_source_exists(self):
        source = Mock()
        source.budget.day = '2026-10-15'
        source.page.return_value = {'title': 'Glass Hall', 'entity': 'Q1', 'lat': 51, 'lng': 0,
                                    'text': ('The Glass Hall is in Eastport beside Market Park. ' * 30)}
        source.request.return_value = {'query': {'geosearch': []}}
        source.entities.return_value = {'Q1': {'claims': {}}}
        external = {'text': ('Glass Hall hosted the first demonstration of a solar railway. ' * 24),
                    'url': 'https://unlisted-source.example/story', 'source_key': 'external',
                    'source_name': 'unlisted-source.example'}
        with patch.object(story, 'linked_public_urls', return_value=[external['url']]), \
             patch.object(story, 'public_page', return_value=external) as fetch:
            targets = story.source_targets([{'title': 'Glass Hall', 'place_type': 'museum'}],
                                           source, [], [], [], {'rejections': []})
        fetch.assert_called_once_with(source, external['url'], 'Glass Hall')
        self.assertEqual(targets[0]['official']['source_key'], 'external')
        self.assertTrue(any(p['source'] == 'unlisted-source.example' for p in targets[0]['passages']))

    def test_discovery_stops_before_clue_generation_without_sourced_story(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Mock()
            provider.clients = [SimpleNamespace(config=SimpleNamespace(gemini_api_key='secret'))]
            provider.requests = []
            provider.call_with_fallback.side_effect = [
                {'targets': [{'title': f'Place {i}', 'place_type': 'museum'} for i in range(12)]},
                {'ranked': [{'title': 'Place 0', 'passage_id': 'p0', 'hook': 'Invented story with no source support.',
                             'city_title': 'Invented City', 'local_title': 'Invented Park'}]},
            ]
            source = Mock()
            source.budget.day = '2026-10-15'
            source.page.side_effect = lambda name: {'title': name, 'entity': 'Q1', 'lat': 51, 'lng': 0,
                                                     'text': 'This place stands beside the river. ' * 30}
            source.entities.return_value = {'Q1': {'claims': {}}}
            budget = Mock()
            budget.day = '2026-10-15'
            budget.budget_day = '2026-10-15'
            budget.attempt_number = 1
            budget.finish.return_value = {'model': 2, 'source': 12}
            with patch.object(story.legacy, 'history', return_value=[]):
                result = story.discover(source_db=Path(directory) / 'db', catalog=None,
                                        puzzle_date='2026-10-17', output_dir=Path(directory),
                                        budget=budget, provider=provider, sources=source)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('No story named source-backed', result['error'])
            self.assertEqual(provider.call_with_fallback.call_count, 2)


if __name__ == '__main__':
    unittest.main()
