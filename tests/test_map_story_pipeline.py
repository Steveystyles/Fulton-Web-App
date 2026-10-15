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
                                    budget=budget, provider=provider, sources=Mock())
            self.assertEqual(report['status'], 'needs_source_review', report.get('error'))
            self.assertFalse(report['production_modified'])
            self.assertTrue(Path(report['report_path']).exists())
            self.assertEqual(provider.call_with_fallback.call_count, 3)

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

    def test_unesco_identity_requires_direct_wikidata_identifier(self):
        def claim(value):
            return {'rank': 'normal', 'mainsnak': {'snaktype': 'value',
                    'datavalue': {'value': value}}}
        self.assertEqual(story.unesco_id({'claims': {'P757': [claim('252')]}}), '252')
        self.assertIsNone(story.unesco_id({'claims': {'P757': [claim('https://other.example/')]}}))
        self.assertIsNone(story.unesco_id({'claims': {}}))

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
