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
FACT_IMAGE_TIMEOUT_SEC = int(os.environ.get("FULTONS_FACT_IMAGE_TIMEOUT_SEC", "12"))
FACT_IMAGE_OPENAI_MODEL = os.environ.get("FULTONS_FACT_IMAGE_OPENAI_MODEL", server.QUIZ_OPENAI_MODEL)
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
GENERIC_IMAGE_TERMS = ("arms", "badge", "coat_of_arms", "diagram", "flag", "icon", "locator", "logo", "map", "seal", "shield", "symbol")


def session_header(token: str) -> str:
    max_age = server.SESSION_DAYS * 24 * 60 * 60
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{server.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"


def clear_session_header() -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{server.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"


def _json_request(url: str, *, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = FACT_IMAGE_TIMEOUT_SEC) -> dict[str, Any]:
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


def _clean_subject(value: str) -> str:
    value = re.sub(r"[\"'`“”]+", "", value).strip()
    value = re.sub(r"^(subject|entity|query)\s*:\s*", "", value, flags=re.I).strip()
    return value.split("\n", 1)[0].strip(" .,-")[:90]


def _fallback_subjects(title: str, text: str, place_title: str) -> list[str]:
    fact = f"{title}. {text}"
    place = place_title.split(",", 1)[0].strip().lower()
    subjects: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[A-Z][A-Za-z0-9'&.-]+(?:\s+(?:of|and|the|[A-Z][A-Za-z0-9'&.-]+)){0,5}", fact):
        subject = _clean_subject(match.group(0))
        key = subject.lower()
        if len(subject) >= 4 and key != place and key not in seen:
            subjects.append(subject)
            seen.add(key)
    for candidate in (title, f"{title} {place_title}", text):
        subject = _clean_subject(candidate)
        key = subject.lower()
        if len(subject) >= 4 and key not in seen:
            subjects.append(subject)
            seen.add(key)
    return subjects[:8]


def _llm_subjects(title: str, text: str, place_title: str) -> list[str]:
    api_key = server.QUIZ_OPENAI_API_KEY
    if not api_key:
        return []
    payload = {
        "model": FACT_IMAGE_OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "Return JSON only: {\"subjects\":[...]} with up to 4 specific visual entities for a historical fact image search. Do not choose the town unless the fact is only about the town."},
            {"role": "user", "content": f"Title: {title}\nFact: {text}\nLocation: {place_title}"},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        headers = {"Authorization": "Bearer " + api_key}
        response = _json_request("https://api.openai.com/v1/chat/completions", data=payload, headers=headers, timeout=server.QUIZ_OPENAI_TIMEOUT_SEC)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        subjects = parsed.get("subjects", [])
        if isinstance(subjects, list):
            return [_clean_subject(str(subject)) for subject in subjects if _clean_subject(str(subject))]
    except Exception as error:
        server.safe_log(f"Fact image subject extraction failed: {error}")
    return []


def _subjects(title: str, text: str, place_title: str) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for subject in [*_llm_subjects(title, text, place_title), *_fallback_subjects(title, text, place_title)]:
        key = subject.lower()
        if subject and key not in seen:
            seen.add(key)
            output.append(subject)
    return output[:8]


def _generic_image_url(url: str) -> bool:
    value = url.lower().replace("%20", "_").replace("-", "_")
    return any(term in value for term in GENERIC_IMAGE_TERMS)


def _image_from_summary(summary: dict[str, Any], subject: str) -> dict[str, Any] | None:
    source_url = None
    content_urls = summary.get("content_urls")
    if isinstance(content_urls, dict):
        source_url = content_urls.get("desktop", {}).get("page")
    title = str(summary.get("title") or subject)
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
            return {"url": image_url, "title": title, "sourceName": "Wikipedia", "sourceUrl": source_url}
    return None


def _wiki_image(subject: str) -> dict[str, Any] | None:
    try:
        summary = _json_request(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(subject.replace(' ', '_'), safe='')}?redirect=true")
        image = _image_from_summary(summary, subject)
        if image:
            return image
    except Exception:
        pass
    try:
        params = urlencode({"action": "query", "format": "json", "list": "search", "srsearch": subject, "srlimit": "5", "origin": "*"})
        payload = _json_request(f"https://en.wikipedia.org/w/api.php?{params}")
        pages = payload.get("query", {}).get("search", [])
    except Exception:
        return None
    for page in pages:
        title = str(page.get("title") or "")
        if not title:
            continue
        try:
            summary = _json_request(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}?redirect=true")
        except Exception:
            continue
        image = _image_from_summary(summary, title)
        if image:
            return image
    return None


def _commons_image(subject: str, title: str, text: str, place_title: str) -> dict[str, Any] | None:
    try:
        image = server.fetch_commons_fact_image({"title": subject or title, "text": text}, place_title)
    except Exception as error:
        server.safe_log(f"Commons fact image lookup failed: {error}")
        return None
    if isinstance(image, dict) and image.get("url"):
        return {
            "url": image.get("url"),
            "title": image.get("title") or subject or title,
            "sourceName": image.get("sourceName") or "Wikimedia Commons",
            "sourceUrl": image.get("sourceUrl"),
        }
    return None


def _unsplash_image(subjects: list[str], place_title: str) -> dict[str, Any] | None:
    if not UNSPLASH_ACCESS_KEY or not subjects:
        return None
    try:
        params = urlencode({"query": f"{subjects[0]} {place_title}".strip(), "orientation": "landscape", "per_page": "1", "client_id": UNSPLASH_ACCESS_KEY})
        payload = _json_request(f"https://api.unsplash.com/search/photos?{params}")
        results = payload.get("results", [])
        if not results:
            return None
        photo = results[0]
        image_url = photo.get("urls", {}).get("regular")
        source_url = photo.get("links", {}).get("html")
        if isinstance(image_url, str) and image_url.startswith("https://"):
            return {"url": image_url, "title": photo.get("description") or photo.get("alt_description") or subjects[0], "sourceName": "Unsplash", "sourceUrl": source_url}
    except Exception as error:
        server.safe_log(f"Unsplash fact image lookup failed: {error}")
    return None


def compute_fact_image(title: str, text: str, place_title: str) -> dict[str, Any]:
    title = title.strip()[:160]
    text = text.strip()[:800]
    place_title = place_title.strip()[:160]
    if not title and not text:
        return _blank_image()
    cache_key = hashlib.sha256(f"{title}\n{text}\n{place_title}".lower().encode("utf-8")).hexdigest()
    if cache_key in FACT_IMAGE_CACHE:
        return FACT_IMAGE_CACHE[cache_key]
    subjects = _subjects(title, text, place_title)
    for subject in subjects:
        image = _wiki_image(subject)
        if image:
            FACT_IMAGE_CACHE[cache_key] = image
            return image
    for subject in subjects[:4]:
        image = _commons_image(subject, title, text, place_title)
        if image:
            FACT_IMAGE_CACHE[cache_key] = image
            return image
    image = _unsplash_image(subjects, place_title) or _blank_image()
    FACT_IMAGE_CACHE[cache_key] = image
    return image


_original_route_api = server.FultonsHandler.route_api


def route_api(self: server.FultonsHandler, method: str, path: str, query: str = "") -> None:
    if path == "/api/fact-image" and method == "POST":
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
