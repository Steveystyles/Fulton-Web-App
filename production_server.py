from __future__ import annotations

import hashlib
import json
import os
import re
from http import HTTPStatus
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import server

COOKIE_SECURE = os.environ.get("FULTONS_COOKIE_SECURE", "1") == "1"
FACT_IMAGE_CACHE: dict[str, dict[str, Any]] = {}
FACT_IMAGE_TIMEOUT_SEC = int(os.environ.get("FULTONS_FACT_IMAGE_TIMEOUT_SEC", "18"))
FACT_IMAGE_OPENAI_MODEL = os.environ.get("FULTONS_FACT_IMAGE_OPENAI_MODEL", server.OPENAI_MODEL)
GENERIC_IMAGE_TERMS = (
    "arms",
    "badge",
    "coat_of_arms",
    "diagram",
    "flag",
    "icon",
    "locator",
    "logo",
    "map",
    "seal",
    "shield",
    "symbol",
)
GENERIC_QUERY_TERMS = {
    "architecture",
    "building",
    "buildings",
    "castle",
    "church",
    "city",
    "culture",
    "event",
    "factory",
    "history",
    "industry",
    "landmark",
    "monument",
    "museum",
    "people",
    "place",
    "railway",
    "river",
    "school",
    "street",
    "town",
    "village",
}


def session_header(token: str) -> str:
    max_age = server.SESSION_DAYS * 24 * 60 * 60
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{server.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"


def clear_session_header() -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{server.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"


def _api_key() -> str:
    return (
        os.environ.get("FULTONS_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or server.OPENAI_API_KEY
        or ""
    )


def _json_request(
    url: str,
    *,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = FACT_IMAGE_TIMEOUT_SEC,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json", "User-Agent": server.HISTORY_USER_AGENT}
    if headers:
        request_headers.update(headers)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _blank_image() -> dict[str, Any]:
    return {"url": None, "title": "", "sourceName": "", "sourceUrl": None}


def _clean(value: str, limit: int = 120) -> str:
    value = re.sub(r"[\"'`“”]+", "", value).strip()
    value = re.sub(r"^(subject|entity|query|image)\s*:\s*", "", value, flags=re.I).strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,-")[:limit]


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", value.lower()).strip()


def _is_generic_query(value: str, place_title: str) -> bool:
    normalised = _normalise(value)
    place = _normalise(place_title.split(",", 1)[0])
    if not normalised or normalised == place:
        return True
    words = {word for word in normalised.split() if word}
    if normalised in GENERIC_QUERY_TERMS:
        return True
    if words and words.issubset(GENERIC_QUERY_TERMS):
        return True
    if normalised.startswith("history of ") or normalised.startswith("list of "):
        return True
    return False


def _fallback_queries(title: str, text: str, place_title: str) -> list[str]:
    fact = f"{title}. {text}"
    output: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[A-Z][A-Za-z0-9'&.-]+(?:\s+(?:of|and|the|[A-Z][A-Za-z0-9'&.-]+)){0,6}", fact):
        query = _clean(match.group(0), 100)
        key = query.lower()
        if len(query) >= 4 and key not in seen and not _is_generic_query(query, place_title):
            output.append(query)
            seen.add(key)
    for candidate in (title, f"{title} {place_title}"):
        query = _clean(candidate, 100)
        key = query.lower()
        if len(query) >= 4 and key not in seen and not _is_generic_query(query, place_title):
            output.append(query)
            seen.add(key)
    return output[:8]


def _planned_queries(title: str, text: str, place_title: str) -> list[str]:
    fallback = _fallback_queries(title, text, place_title)
    api_key = _api_key()
    if not api_key:
        return fallback
    payload = {
        "model": FACT_IMAGE_OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return JSON only: {\"queries\":[...]} . Create up to 6 image search queries for the exact completed fact card. "
                    "Queries must be named, visual subjects from the fact text: a specific building, person, organisation, event, factory, artwork, ship, street, or landmark. "
                    "Do not return broad categories, themes, the town alone, the location alone, or words like history, industry, culture, architecture, landmark, people, or event."
                ),
            },
            {"role": "user", "content": f"Title: {title}\nFact: {text}\nLocation: {place_title}"},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        response = _json_request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Authorization": "Bearer " + api_key},
            timeout=server.OPENAI_TIMEOUT_SEC,
        )
        parsed = json.loads(response.get("choices", [{}])[0].get("message", {}).get("content", "{}"))
        raw_queries = parsed.get("queries", [])
        queries = []
        if isinstance(raw_queries, list):
            for raw_query in raw_queries:
                query = _clean(str(raw_query), 100)
                if query and not _is_generic_query(query, place_title):
                    queries.append(query)
        seen = {query.lower() for query in queries}
        queries.extend(query for query in fallback if query.lower() not in seen)
        return queries[:8]
    except Exception as error:
        server.safe_log(f"Fact image query planning failed: {error}")
        return fallback


def _generic_image_url(url: str) -> bool:
    value = url.lower().replace("%20", "_").replace("-", "_")
    return any(term in value for term in GENERIC_IMAGE_TERMS)


def _candidate_from_summary(summary: dict[str, Any], query: str) -> dict[str, Any] | None:
    source_url = None
    content_urls = summary.get("content_urls")
    if isinstance(content_urls, dict):
        source_url = content_urls.get("desktop", {}).get("page")
    title = str(summary.get("title") or query)
    description = str(summary.get("description") or "")
    extract = str(summary.get("extract") or "")
    if _is_generic_query(title, query):
        return None
    for key in ("originalimage", "thumbnail"):
        image = summary.get(key)
        if not isinstance(image, dict):
            continue
        image_url = str(image.get("source") or "")
        if not image_url.startswith("https://") or _generic_image_url(image_url):
            continue
        width = int(image.get("width") or 0)
        height = int(image.get("height") or 0)
        if width >= 240 and height >= 120:
            return {
                "url": image_url,
                "title": title,
                "sourceName": "Wikipedia",
                "sourceUrl": source_url,
                "candidateText": f"{title}. {description}. {extract}"[:1000],
            }
    return None


def _wiki_candidates(query: str) -> list[dict[str, Any]]:
    titles = [query]
    try:
        params = urlencode({"action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": "6", "origin": "*"})
        payload = _json_request(f"https://en.wikipedia.org/w/api.php?{params}")
        titles.extend(str(page.get("title") or "") for page in payload.get("query", {}).get("search", []))
    except Exception:
        pass
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title in titles:
        title = title.strip()
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        try:
            summary = _json_request(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}?redirect=true")
        except Exception:
            continue
        candidate = _candidate_from_summary(summary, query)
        if candidate:
            output.append(candidate)
    return output


def _commons_candidates(query: str) -> list[dict[str, Any]]:
    try:
        params = urlencode({
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrlimit": "8",
            "gsrsearch": query,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": "960",
            "origin": "*",
        })
        payload = _json_request(f"https://commons.wikimedia.org/w/api.php?{params}")
    except Exception:
        return []
    pages = payload.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        return []
    output: list[dict[str, Any]] = []
    for page in pages.values():
        title = str(page.get("title") or "").replace("File:", "", 1)
        info = (page.get("imageinfo") or [{}])[0]
        image_url = str(info.get("thumburl") or info.get("url") or "")
        if not image_url.startswith("https://") or _generic_image_url(image_url):
            continue
        metadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        description = str((metadata.get("ImageDescription") or {}).get("value") or "")
        clean_description = re.sub(r"<[^>]+>", " ", description)
        output.append({
            "url": image_url,
            "title": title,
            "sourceName": "Wikimedia Commons",
            "sourceUrl": info.get("descriptionurl"),
            "candidateText": f"{title}. {clean_description}"[:1000],
        })
    return output


def _choose_relevant_candidate(title: str, text: str, place_title: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    api_key = _api_key()
    if not api_key:
        return None
    compact_candidates = [
        {"index": index, "title": item.get("title"), "source": item.get("sourceName"), "text": item.get("candidateText", "")[:600]}
        for index, item in enumerate(candidates[:12])
    ]
    payload = {
        "model": FACT_IMAGE_OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return JSON only: {\"index\": number|null, \"reason\": string}. Pick an image only if it clearly matches the exact fact card content. "
                    "Return null for category images, town-only/place-only images, generic architecture, maps, flags, logos, broad history pages, or weakly related images. "
                    "It is better to return null than to choose a generic or merely attractive image."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "fact_card": {"title": title, "text": text, "location": place_title},
                    "candidates": compact_candidates,
                }),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        response = _json_request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Authorization": "Bearer " + api_key},
            timeout=server.OPENAI_TIMEOUT_SEC,
        )
        parsed = json.loads(response.get("choices", [{}])[0].get("message", {}).get("content", "{}"))
        index = parsed.get("index")
        if isinstance(index, int) and 0 <= index < len(candidates[:12]):
            chosen = dict(candidates[index])
            chosen.pop("candidateText", None)
            return chosen
    except Exception as error:
        server.safe_log(f"Fact image relevance judging failed: {error}")
    return None


def compute_fact_image(title: str, text: str, place_title: str) -> dict[str, Any]:
    title = title.strip()[:160]
    text = text.strip()[:1000]
    place_title = place_title.strip()[:160]
    if not title and not text:
        return _blank_image()
    cache_key = hashlib.sha256(f"strict-v1\n{title}\n{text}\n{place_title}".lower().encode("utf-8")).hexdigest()
    if cache_key in FACT_IMAGE_CACHE:
        return FACT_IMAGE_CACHE[cache_key]
    candidates: list[dict[str, Any]] = []
    for query in _planned_queries(title, text, place_title):
        candidates.extend(_wiki_candidates(query))
        candidates.extend(_commons_candidates(query))
    result = _choose_relevant_candidate(title, text, place_title, candidates) or _blank_image()
    FACT_IMAGE_CACHE[cache_key] = result
    return result


_original_route_api = server.FultonsHandler.route_api


def route_api(self: server.FultonsHandler, method: str, path: str, query: str = "") -> None:
    if path == "/api/fact-image" and method == "POST":
        with server.connect_db() as conn:
            token = server.get_cookie_value(self.headers, server.SESSION_COOKIE)
            user = server.current_user(conn, token)
            if user is None:
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                return

        payload = self.read_json()
        self.send_json(
            HTTPStatus.OK,
            compute_fact_image(
                str(payload.get("title") or ""),
                str(payload.get("text") or ""),
                str(payload.get("placeTitle") or ""),
            ),
        )
        return
    _original_route_api(self, method, path, query)


def apply_hardening() -> None:
    server.COOKIE_SECURE = COOKIE_SECURE
    server.session_header = session_header
    server.clear_session_header = clear_session_header
    server.FultonsHandler.route_api = route_api


if __name__ == "__main__":
    apply_hardening()
    server.run()
