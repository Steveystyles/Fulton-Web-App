"""Public-geocoding fallback must respect OSM's shared-service policy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import map_geocoding as geo


class GeocodingTests(unittest.TestCase):
    def test_search_is_cached_and_paced_across_queries(self):
        row = {'lat': '51.5001', 'lon': '-0.1269', 'osm_type': 'way', 'osm_id': 123,
               'display_name': 'Glass Hall, London, United Kingdom',
               'category': 'tourism', 'type': 'museum',
               'address': {'country_code': 'gb', 'country': 'United Kingdom', 'city': 'London'},
               'extratags': {'website': 'https://example.org/', 'wikidata': 'Q123'}}
        response = Mock(status=200)
        response.read.return_value = json.dumps([row]).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        clock = Mock(return_value=1000.0)
        sleep = Mock()
        budget = Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(geo.http.client, 'HTTPSConnection', return_value=connection) as factory:
            cache = Path(directory) / 'geocode.sqlite3'
            first = geo.NominatimSource(cache, budget, clock=clock, sleep=sleep)
            result = first.search('Glass Hall')
            self.assertEqual(result[0]['country_code'], 'GB')
            self.assertEqual(result[0]['url'], 'https://www.openstreetmap.org/way/123')
            second = geo.NominatimSource(cache, budget, clock=clock, sleep=sleep)
            self.assertEqual(second.search('glass hall'), result)
            second.search('Market Park')
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(budget.spend.call_count, 2)
        sleep.assert_called_once_with(geo.MIN_INTERVAL_SECONDS)
        self.assertTrue(connection.request.call_args.args[1].startswith('/search?'))
        self.assertIn('FultonsMapSelector', connection.request.call_args.kwargs['headers']['User-Agent'])

    def test_invalid_name_and_coordinates_do_not_become_map_candidates(self):
        for name in ('', '  ', 'A\nB'):
            with self.assertRaises(ValueError):
                geo._name(name)
        self.assertIsNone(geo._normalize_row({'lat': 'nan', 'lon': '1',
                                               'osm_type': 'way', 'osm_id': 1}))
        self.assertIsNone(geo._normalize_row({'lat': '51', 'lon': '181',
                                               'osm_type': 'way', 'osm_id': 1}))


if __name__ == '__main__':
    unittest.main()
