"""Cached, policy-paced public geocoding for Map discovery fallbacks.

The public Nominatim server is not a bulk search index. This adapter only
looks up exact candidate/anchor names after the existing source path fails.
It keeps a persistent cache and spaces network requests at least 15 seconds
apart across processes. No details scraping, autocomplete or grid search.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode


HOST = 'nominatim.openstreetmap.org'
USER_AGENT = 'FultonsMapSelector/1.0 (https://fultons-quiz.co.uk)'
MIN_INTERVAL_SECONDS = 15.0
MAX_RESPONSE_BYTES = 500_000
CACHE_DAYS = 90


def _name(value: str) -> str:
    if (not isinstance(value, str) or not 3 <= len(value.strip()) <= 160 or
            any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid public place-search name.')
    return ' '.join(value.split())


def _normalize_row(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    try:
        lat, lng = float(row['lat']), float(row['lon'])
        osm_type, osm_id = str(row['osm_type']), int(row['osm_id'])
    except (KeyError, TypeError, ValueError):
        return None
    if (not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or
            not -180 <= lng <= 180 or osm_type not in ('node', 'way', 'relation') or osm_id <= 0):
        return None
    address = row.get('address') if isinstance(row.get('address'), dict) else {}
    extras = row.get('extratags') if isinstance(row.get('extratags'), dict) else {}
    named = row.get('namedetails') if isinstance(row.get('namedetails'), dict) else {}
    display = str(row.get('display_name') or '')[:400]
    name = str(named.get('name:en') or named.get('name') or display.split(',')[0]).strip()[:160]
    if not name:
        return None
    return {'name': name, 'display_name': display, 'lat': lat, 'lng': lng,
            'osm_type': osm_type, 'osm_id': osm_id,
            'category': str(row.get('category') or '')[:60],
            'type': str(row.get('type') or '')[:60],
            'country_code': str(address.get('country_code') or '').upper()[:2],
            'country_name': str(address.get('country') or '')[:100],
            'city': str(address.get('city') or address.get('town') or address.get('village') or '')[:100],
            'website': str(extras.get('website') or extras.get('contact:website') or '')[:2048],
            'wikidata': str(extras.get('wikidata') or '')[:30],
            'url': f'https://www.openstreetmap.org/{osm_type}/{osm_id}'}


class NominatimSource:
    def __init__(self, cache_path: Path, budget, *, clock=None, sleep=None):
        self.cache_path = cache_path
        self.budget = budget
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(cache_path)) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS map_geocode_cache('
                         'query TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, result TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS map_geocode_meta('
                         'key TEXT PRIMARY KEY, value REAL NOT NULL)')
            conn.commit()

    def _cached(self, query: str) -> list[dict] | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()
        with closing(sqlite3.connect(self.cache_path)) as conn:
            row = conn.execute('SELECT result FROM map_geocode_cache WHERE query=? AND fetched_at>=?',
                               (query, cutoff)).fetchone()
        return json.loads(row[0]) if row else None

    def _reserve(self) -> None:
        with closing(sqlite3.connect(self.cache_path, timeout=30)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT value FROM map_geocode_meta WHERE key='last_request_at'").fetchone()
            current = self.clock()
            reserved = max(current, (row[0] + MIN_INTERVAL_SECONDS) if row else current)
            conn.execute("INSERT INTO map_geocode_meta(key,value) VALUES('last_request_at',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (reserved,))
            conn.commit()
        if reserved > current:
            self.sleep(reserved - current)

    def search(self, name: str) -> list[dict]:
        query = _name(name)
        cached = self._cached(query.casefold())
        if cached is not None:
            return cached
        self._reserve()
        self.budget.spend('source')
        path = '/search?' + urlencode({'q': query, 'format': 'jsonv2', 'limit': 3,
                                       'addressdetails': 1, 'extratags': 1, 'namedetails': 1})
        conn = http.client.HTTPSConnection(HOST, timeout=20)
        try:
            conn.request('GET', path, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            response = conn.getresponse()
            if response.status != 200:
                raise RuntimeError(f'Geocoder returned HTTP {response.status}.')
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('Geocoder response exceeded the size limit.')
        finally:
            conn.close()
        rows = json.loads(body)
        if not isinstance(rows, list) or len(rows) > 3:
            raise ValueError('Geocoder returned an invalid result set.')
        result = [normalized for row in rows if (normalized := _normalize_row(row)) is not None]
        with closing(sqlite3.connect(self.cache_path)) as conn:
            conn.execute('INSERT INTO map_geocode_cache(query,fetched_at,result) VALUES(?,?,?) '
                         'ON CONFLICT(query) DO UPDATE SET fetched_at=excluded.fetched_at,result=excluded.result',
                         (query.casefold(), datetime.now(timezone.utc).isoformat(), json.dumps(result)))
            conn.commit()
        return result
