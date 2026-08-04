from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree


USER_AGENT = "FultonsQuizEvidence/1.0 (+https://fultons-quiz.co.uk)"

BLOCKED_SOURCE_HOSTS = (
    "facebook.com",
    "instagram.com",
    "pinterest.",
    "quora.com",
    "reddit.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
)

PRIMARY_SOURCE_HOSTS = (
    "fifa.com",
    "uefa.com",
    "olympics.com",
    "premierleague.com",
    "thefa.com",
    "nationalarchives.gov.uk",
    "loc.gov",
    "si.edu",
)

REPUTABLE_SOURCE_HOSTS = (
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
    "britannica.com",
    "history.com",
    "nationalgeographic.com",
    "reuters.com",
)

STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "among",
    "answer",
    "associated",
    "before",
    "being",
    "became",
    "become",
    "between",
    "could",
    "detail",
    "does",
    "during",
    "example",
    "following",
    "from",
    "have",
    "historical",
    "into",
    "known",
    "linked",
    "matches",
    "most",
    "only",
    "question",
    "rather",
    "than",
    "that",
    "their",
    "this",
    "through",
    "what",
    "when",
    "where",
    "which",
    "while",
    "whose",
    "with",
    "would",
}

GENERIC_CLAIM_TERMS = {
    "answer",
    "camera",
    "city",
    "club",
    "competition",
    "country",
    "event",
    "game",
    "match",
    "nation",
    "place",
    "player",
    "stadium",
    "team",
    "tournament",
    "world",
}

RISK_PATTERNS = {
    "first_or_earliest": re.compile(r"\b(?:first(?:-ever)?|earliest|pioneer(?:ed|ing)?)\b", re.I),
    "only_or_unique": re.compile(
        r"\b(?:only(?!\s+(?:answer|choice|option))|unique|sole)\b",
        re.I,
    ),
    "record_or_superlative": re.compile(
        r"\b(?:record(?:-holding| holder)?|oldest|youngest|largest|smallest|fastest|slowest|"
        r"highest|lowest|longest|shortest|most|least|greatest)\b",
        re.I,
    ),
    "invention_or_discovery": re.compile(r"\b(?:invented|discovered|created|introduced|founded)\b", re.I),
    "specific_year": re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b"),
    "century_qualifier": re.compile(
        r"\b(?:early|mid(?:dle)?|late)[ -]+(?:[1-9]|1[0-9]|20)(?:st|nd|rd|th) century\b",
        re.I,
    ),
}

RISK_SIGNAL_ALIASES = {
    "first_or_earliest": ("first", "earliest", "pioneer"),
    "only_or_unique": ("only", "unique", "sole"),
    "record_or_superlative": (
        "record",
        "oldest",
        "youngest",
        "largest",
        "smallest",
        "fastest",
        "slowest",
        "highest",
        "lowest",
        "longest",
        "shortest",
        "most",
        "least",
        "greatest",
    ),
    "invention_or_discovery": ("invent", "discover", "create", "introduc", "found"),
}


class EvidenceSearchUnavailable(RuntimeError):
    """Raised when every evidence-search request fails before returning results."""


def openrouter_response_evidence(
    payload: dict[str, Any],
    *,
    timeout_sec: int,
    query: str,
) -> list[dict[str, str]]:
    try:
        message = payload["choices"][0]["message"]
    except (IndexError, KeyError, TypeError) as error:
        raise EvidenceSearchUnavailable("OpenRouter web search returned no response message.") from error
    annotations = message.get("annotations") if isinstance(message, dict) else None
    if not isinstance(annotations, list):
        annotations = []

    evidence: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
            continue
        citation = annotation.get("url_citation")
        if not isinstance(citation, dict):
            citation = annotation
        url = str(citation.get("url") or "").strip().split("#", 1)[0]
        normalized_url = url.casefold().rstrip("/")
        if (
            not url.startswith(("http://", "https://"))
            or blocked_source(url)
            or normalized_url in seen_urls
        ):
            continue
        seen_urls.add(normalized_url)
        title = clean_text(citation.get("title"), 220) or source_host(url)
        content = clean_text(citation.get("content"), 1800)
        if len(content) < 25:
            content = fetch_page_excerpt(url, timeout_sec=timeout_sec)
        if len(content) < 25:
            continue
        evidence.append(
            {
                "title": title,
                "source_name": source_host(url),
                "source_url": url,
                "tier": source_tier(url),
                "snippet": content[:900],
                "excerpt": content,
                "query": query,
            }
        )
    return evidence


def collect_openrouter_question_evidence(
    question: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout_sec: int = 90,
    max_results: int = 8,
) -> list[dict[str, str]]:
    if not api_key.strip():
        raise EvidenceSearchUnavailable("OpenRouter web search has no API key.")
    claim = " ".join(
        str(question.get(field) or "").strip()
        for field in ("question", "correct_answer", "explanation")
    ).strip()
    prompt = f"""Research this proposed quiz question using web search.

Question: {question.get('question')}
Proposed answer: {question.get('correct_answer')}
Explanation: {question.get('explanation')}

Find reliable sources that explicitly support or contradict the exact material
claim. Prioritize official institutions, governing bodies, universities, museums,
major reference works, and reputable news archives. Search specifically for every
date, first/only/record/superlative, invention, discovery, or century qualifier.
Do not assume the claim is true. Return a concise evidence summary with citations.
"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "max_results": max(2, max_results),
                    "max_total_results": max(2, max_results),
                    "search_context_size": "medium",
                },
            }
        ],
        "temperature": 0,
        "max_tokens": 700,
        "stream": False,
    }
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://fultons-quiz.co.uk",
            "X-Title": "Fultons Quiz Evidence",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(10, timeout_sec)) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = clean_text(error.read().decode("utf-8", errors="replace"), 500)
        except OSError:
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise EvidenceSearchUnavailable(
            f"OpenRouter evidence search failed with HTTP {error.code}{suffix}"
        ) from error
    except (TimeoutError, URLError, OSError, json.JSONDecodeError) as error:
        raise EvidenceSearchUnavailable(f"OpenRouter evidence search failed: {error}") from error

    evidence = openrouter_response_evidence(
        response_payload,
        timeout_sec=timeout_sec,
        query=claim,
    )
    if not evidence:
        raise EvidenceSearchUnavailable("OpenRouter evidence search returned no usable citations.")
    return evidence


def clean_text(value: Any, limit: int = 1200) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def normalized_tokens(value: Any) -> list[str]:
    return normalize_text(value).split()


def token_stem(token: str) -> str:
    for suffix in ("ly", "ingly", "edly", "ment", "ness", "ing", "ied", "ed", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            return token[: -len(suffix)]
    return token


def source_host(url: str) -> str:
    return urlparse(url).netloc.casefold().split(":", 1)[0].removeprefix("www.")


def blocked_source(url: str) -> bool:
    host = source_host(url)
    return not host or any(blocked in host for blocked in BLOCKED_SOURCE_HOSTS)


def source_tier(url: str) -> str:
    host = source_host(url)
    if (
        host.endswith((".gov", ".gov.uk", ".edu", ".ac.uk"))
        or any(host == item or host.endswith(f".{item}") for item in PRIMARY_SOURCE_HOSTS)
        or any(token in host for token in ("museum", "archives", "university"))
    ):
        return "primary"
    if any(host == item or host.endswith(f".{item}") for item in REPUTABLE_SOURCE_HOSTS):
        return "reputable"
    if host.endswith("wikipedia.org"):
        return "reference"
    return "other"


def source_rank(url: str) -> int:
    return {"primary": 4, "reputable": 3, "reference": 2, "other": 1}[source_tier(url)]


class EvidenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[str] = []
        self.blocks: list[str] = []
        self._active_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag == "meta":
            name = attr_map.get("name", "").casefold()
            prop = attr_map.get("property", "").casefold()
            if name in {"description", "twitter:description"} or prop == "og:description":
                value = clean_text(attr_map.get("content", ""), 500)
                if value:
                    self.meta.append(value)
        elif tag in {"p", "li"}:
            self._active_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active_tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._active_tag:
            return
        value = clean_text(" ".join(self._parts), 700)
        if len(value) >= 40:
            self.blocks.append(value)
        self._active_tag = None
        self._parts = []


def fetch_text(url: str, *, timeout_sec: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_sec) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_page_excerpt(url: str, *, timeout_sec: int) -> str:
    if blocked_source(url):
        return ""
    try:
        parser = EvidenceHTMLParser()
        parser.feed(fetch_text(url, timeout_sec=timeout_sec))
    except Exception:
        return ""
    candidates = [*parser.meta[:2], *parser.blocks[:6]]
    excerpt_parts: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = clean_text(candidate, 700)
        key = normalize_text(cleaned)
        if len(cleaned) < 40 or not key or key in seen:
            continue
        seen.add(key)
        excerpt_parts.append(cleaned)
        if len(" ".join(excerpt_parts)) >= 700 or len(excerpt_parts) >= 3:
            break
    return clean_text(" ".join(excerpt_parts), 1000)


def substantive_words(value: Any, *, answer: str = "", limit: int = 9) -> list[str]:
    answer_tokens = set(normalized_tokens(answer))
    words: list[str] = []
    seen: set[str] = set()
    for token in normalized_tokens(value):
        if len(token) < 4 or token in STOP_WORDS or token in answer_tokens or token in seen:
            continue
        seen.add(token)
        words.append(token)
        if len(words) >= limit:
            break
    return words


def question_search_queries(question: dict[str, Any]) -> list[str]:
    answer = clean_text(question.get("correct_answer"), 140).replace('"', "")
    prompt_words = substantive_words(question.get("question"), answer=answer)
    explanation_words = substantive_words(question.get("explanation"), answer=answer)
    tag_words = substantive_words(" ".join(question.get("tags") or []), answer=answer, limit=5)
    groups = [prompt_words, explanation_words, tag_words]
    queries: list[str] = []
    for words in groups:
        query = f'"{answer}" {" ".join(words)}'.strip()
        if answer and words and query not in queries:
            queries.append(query)
    if answer and not queries:
        queries.append(f'"{answer}" fact history')
    return queries[:3]


def bing_rss_url(query: str) -> str:
    return f"https://www.bing.com/search?format=rss&mkt=en-GB&q={quote_plus(query)}"


def collect_question_evidence(
    question: dict[str, Any],
    *,
    timeout_sec: int = 8,
    max_results: int = 8,
) -> list[dict[str, str]]:
    queries = question_search_queries(question)
    if not queries:
        return []

    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    successful_queries = 0
    errors: list[str] = []
    for query in queries:
        try:
            root = ElementTree.fromstring(fetch_text(bing_rss_url(query), timeout_sec=timeout_sec))
            successful_queries += 1
        except Exception as error:
            errors.append(str(error))
            continue
        for item in root.findall(".//item"):
            title = clean_text(item.findtext("title", default=""), 220)
            url = str(item.findtext("link", default="") or "").strip().split("#", 1)[0]
            snippet = clean_text(item.findtext("description", default=""), 700)
            if not title or not url.startswith(("http://", "https://")) or blocked_source(url):
                continue
            if url in seen_urls or len(snippet) < 25:
                continue
            seen_urls.add(url)
            candidates.append({"title": title, "url": url, "snippet": snippet, "query": query})

    if successful_queries == 0:
        detail = errors[-1][:300] if errors else "unknown search failure"
        raise EvidenceSearchUnavailable(f"Evidence search unavailable: {detail}")

    candidates.sort(
        key=lambda item: (source_rank(item["url"]), len(item["snippet"])),
        reverse=True,
    )
    selected: list[dict[str, str]] = []
    host_counts: dict[str, int] = {}
    for candidate in candidates:
        host = source_host(candidate["url"])
        if host_counts.get(host, 0) >= 2:
            continue
        host_counts[host] = host_counts.get(host, 0) + 1
        selected.append(candidate)
        if len(selected) >= max(1, max_results):
            break

    evidence: list[dict[str, str]] = []
    for candidate in selected:
        url = candidate["url"]
        evidence.append(
            {
                "title": candidate["title"],
                "source_name": source_host(url),
                "source_url": url,
                "tier": source_tier(url),
                "snippet": candidate["snippet"],
                "excerpt": fetch_page_excerpt(url, timeout_sec=timeout_sec) or candidate["snippet"],
                "query": candidate["query"],
            }
        )
    return evidence


def question_risk_profile(question: dict[str, Any]) -> dict[str, Any]:
    claim_text = " ".join(
        str(question.get(field) or "")
        for field in ("question", "explanation")
    )
    signals = [name for name, pattern in RISK_PATTERNS.items() if pattern.search(claim_text)]
    high_risk = bool(signals)
    return {
        "high_risk": high_risk,
        "signals": signals,
        "required_independent_sources": 2 if high_risk else 1,
        "requires_primary_or_reputable": high_risk,
        "claim_anchor_terms": claim_anchor_terms(question, signals),
    }


def claim_anchor_terms(question: dict[str, Any], signals: list[str]) -> list[str]:
    text = " ".join(str(question.get(field) or "") for field in ("question", "explanation"))
    tokens = normalized_tokens(text)
    answer_tokens = set(normalized_tokens(question.get("correct_answer")))
    anchors: list[str] = []

    for token in tokens:
        if re.fullmatch(r"(?:1[0-9]{3}|20[0-9]{2})", token) and token not in anchors:
            anchors.append(token)

    risk_positions = [
        index
        for index, token in enumerate(tokens)
        if any(token.startswith(alias) for aliases in RISK_SIGNAL_ALIASES.values() for alias in aliases)
    ]
    nearby: list[str] = []
    for position in risk_positions:
        for token in tokens[max(0, position - 3) : position + 7]:
            if (
                len(token) >= 6
                and token not in STOP_WORDS
                and token not in GENERIC_CLAIM_TERMS
                and token not in answer_tokens
                and not token.isdigit()
            ):
                nearby.append(token)
    for token in sorted(set(nearby), key=lambda value: (-len(value), nearby.index(value)))[:2]:
        stem = token_stem(token)
        if stem and stem not in anchors:
            anchors.append(stem)

    if "century_qualifier" in signals:
        match = RISK_PATTERNS["century_qualifier"].search(text)
        if match:
            qualifier = normalize_text(match.group(0))
            if qualifier not in anchors:
                anchors.append(qualifier)
    return anchors[:5]


def evidence_item_text(item: dict[str, Any]) -> str:
    return normalize_text(
        " ".join(
            str(item.get(field) or "")
            for field in ("title", "snippet", "excerpt")
        )
    )


def evidence_mentions_answer(item: dict[str, Any], answer: Any) -> bool:
    answer_tokens = [token for token in normalized_tokens(answer) if token not in {"the", "a", "an"}]
    if not answer_tokens:
        return False
    item_tokens = set(evidence_item_text(item).split())
    return all(token in item_tokens for token in answer_tokens)


def evidence_has_risk_signal(text: str, signals: list[str]) -> bool:
    if not signals:
        return True
    for signal in signals:
        if signal in {"specific_year", "century_qualifier"}:
            continue
        aliases = RISK_SIGNAL_ALIASES.get(signal, ())
        if aliases and not any(alias in text for alias in aliases):
            return False
    return True


def century_qualifier_failure(question: dict[str, Any], evidence: list[dict[str, Any]]) -> str | None:
    claim_text = " ".join(str(question.get(field) or "") for field in ("question", "explanation"))
    match = re.search(
        r"\b(early|mid(?:dle)?|late)[ -]+([1-9]|1[0-9]|20)(?:st|nd|rd|th) century\b",
        claim_text,
        re.I,
    )
    if not match:
        return None
    qualifier = match.group(1).casefold()
    century = int(match.group(2))
    start = (century - 1) * 100 + 1
    end = century * 100
    if qualifier == "early":
        expected_start, expected_end = start, start + 32
    elif qualifier.startswith("mid"):
        expected_start, expected_end = start + 33, start + 65
    else:
        expected_start, expected_end = start + 66, end
    evidence_years = {
        int(year)
        for item in evidence
        for year in re.findall(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", evidence_item_text(item))
        if start <= int(year) <= end
    }
    if evidence_years and not any(expected_start <= year <= expected_end for year in evidence_years):
        years = ", ".join(str(year) for year in sorted(evidence_years))
        return (
            f"The {qualifier} {century}th-century qualifier conflicts with the evidence year(s): {years}."
        )
    return None


def precheck_question_evidence(
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    risk = question_risk_profile(question)
    failures: list[str] = []
    answer_indices = [
        index
        for index, item in enumerate(evidence)
        if evidence_mentions_answer(item, question.get("correct_answer"))
    ]
    answer_hosts = {
        source_host(str(evidence[index].get("source_url") or ""))
        for index in answer_indices
    }
    answer_hosts.discard("")

    required_sources = int(risk["required_independent_sources"])
    if not evidence:
        failures.append("Evidence retrieval returned no usable sources.")
    elif not answer_indices:
        failures.append("No retrieved source explicitly mentions the proposed correct answer.")
    elif len(answer_hosts) < required_sources:
        failures.append(
            f"The claim needs {required_sources} independent sources, but only {len(answer_hosts)} supported the answer."
        )

    if risk["requires_primary_or_reputable"] and answer_indices:
        trusted = any(
            str(evidence[index].get("tier") or source_tier(str(evidence[index].get("source_url") or "")))
            in {"primary", "reputable"}
            for index in answer_indices
        )
        if not trusted:
            failures.append("A risky claim needs at least one primary or reputable source.")

    century_failure = century_qualifier_failure(question, [evidence[index] for index in answer_indices])
    if century_failure:
        failures.append(century_failure)

    qualified_indices: list[int] = []
    if risk["high_risk"] and answer_indices:
        anchor_terms = [
            term
            for term in risk["claim_anchor_terms"]
            if not term.endswith(" century")
        ]
        for index in answer_indices:
            text = evidence_item_text(evidence[index])
            stems = {token_stem(token) for token in text.split()}
            anchors_present = all(
                term in text if " " in term or term.isdigit() else token_stem(term) in stems
                for term in anchor_terms
            )
            if anchors_present and evidence_has_risk_signal(text, list(risk["signals"])):
                qualified_indices.append(index)
        if not qualified_indices and not century_failure:
            missing = ", ".join(risk["claim_anchor_terms"]) or "the qualifying language"
            failures.append(
                "No source explicitly supports the risky claim and its key terms "
                f"({missing})."
            )

    feedback = ""
    if failures:
        feedback = (
            "Use a different, well-sourced fact or remove any unsupported date, record, "
            "superlative, exclusivity, invention, or discovery qualifier."
        )
    return {
        "passed": not failures,
        "failure_reasons": failures,
        "feedback_to_generator": feedback,
        "risk_profile": risk,
        "answer_evidence_indices": answer_indices,
        "qualified_evidence_indices": qualified_indices,
    }
