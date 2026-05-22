import { useEffect, useMemo, useState } from "react";
import { type HistoryFact, type HistoryLocationImage } from "../lib/api";

type WikiPage = {
  pageid?: number;
  title?: string;
  extract?: string;
  fullurl?: string;
  original?: { source?: string; width?: number; height?: number };
  thumbnail?: { source?: string; width?: number; height?: number };
};

type ImageCandidate = {
  image: HistoryLocationImage;
  score: number;
};

const stopWords = new Set([
  "about", "after", "also", "among", "annual", "based", "became", "been", "before",
  "being", "building", "buildings", "called", "centre", "century", "during", "early",
  "fact", "facts", "first", "former", "from", "history", "into", "known", "late",
  "local", "many", "most", "name", "named", "near", "part", "place", "that", "their",
  "this", "today", "town", "used", "were", "which", "with", "would",
]);

const genericImageWords = ["arms", "badge", "coat", "diagram", "flag", "icon", "locator", "logo", "map", "seal", "shield", "symbol"];
const genericArticleWords = ["area", "council", "county", "district", "geography", "history of", "list of", "municipality", "region", "shire", "town", "village"];

function normalise(value: string) {
  return value.toLowerCase().replace(/&[a-z]+;/g, " ").replace(/[^a-z0-9' ]+/g, " ");
}

function terms(text: string, excluded = new Set<string>()) {
  const output = new Set<string>();
  for (const match of normalise(text).matchAll(/[a-z][a-z0-9']+/g)) {
    const term = match[0];
    if (term.length >= 4 && !stopWords.has(term) && !excluded.has(term)) {
      output.add(term);
    }
  }
  return output;
}

function quotedPhrases(text: string) {
  const output: string[] = [];
  for (const match of text.matchAll(/[“"]([^”"]{4,80})[”"]/g)) {
    output.push(match[1].trim());
  }
  return output;
}

function namedPhrases(text: string, placeTitle: string) {
  const place = placeTitle.split(",", 1)[0].trim().toLowerCase();
  const seen = new Set<string>();
  const output: string[] = [];

  for (const phrase of quotedPhrases(text)) {
    const key = phrase.toLowerCase();
    if (!seen.has(key) && key !== place) {
      seen.add(key);
      output.push(phrase);
    }
  }

  for (const match of text.matchAll(/[A-Z][A-Za-z0-9'&.-]+(?:\s+(?:of|and|the|[A-Z][A-Za-z0-9'&.-]+)){0,5}/g)) {
    const phrase = match[0].replace(/\s+/g, " ").trim();
    const key = phrase.toLowerCase();
    if (
      phrase.length >= 4 && key !== place && !seen.has(key) && !stopWords.has(key) &&
      !genericArticleWords.some((word) => key === word || key.startsWith(`${word} `))
    ) {
      seen.add(key);
      output.push(phrase);
    }
  }

  return output;
}

function articleUrl(title: string) {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
}

function isGenericImage(url: string) {
  const normalised = decodeURIComponent(url).toLowerCase();
  return genericImageWords.some((word) => normalised.includes(word));
}

function isGenericArticleTitle(title: string, placeTitle: string) {
  const place = placeTitle.split(",", 1)[0].trim().toLowerCase();
  const value = title.toLowerCase();
  if (value === place) {
    return true;
  }
  return genericArticleWords.some((word) => value === word || value.includes(word));
}

function bestPageImage(page: WikiPage) {
  const original = page.original;
  if (original?.source?.startsWith("https://") && !isGenericImage(original.source)) {
    if ((original.width ?? 0) >= 320 && (original.height ?? 0) >= 160) {
      return original.source;
    }
  }

  const thumbnail = page.thumbnail;
  if (thumbnail?.source?.startsWith("https://") && !isGenericImage(thumbnail.source)) {
    if ((thumbnail.width ?? 0) >= 240 && (thumbnail.height ?? 0) >= 120) {
      return thumbnail.source;
    }
  }

  return null;
}

function scorePage(fact: HistoryFact, page: WikiPage, placeTitle: string) {
  const title = String(page.title ?? "");
  const extract = String(page.extract ?? "");
  const placeTerms = terms(placeTitle);
  const factTerms = terms(`${fact.title} ${fact.text}`, placeTerms);
  const pageTerms = terms(`${title} ${extract}`, placeTerms);
  const titleTerms = terms(title, placeTerms);
  const factText = normalise(`${fact.title} ${fact.text}`);
  let score = 0;

  for (const term of factTerms) {
    if (pageTerms.has(term)) {
      score += titleTerms.has(term) ? 5 : 2;
    }
  }

  for (const phrase of namedPhrases(`${fact.title} ${fact.text}`, placeTitle)) {
    const normalisedPhrase = normalise(phrase).trim();
    if (normalisedPhrase.length >= 4 && normalise(title).includes(normalisedPhrase)) {
      score += 18;
    } else if (normalisedPhrase.length >= 4 && normalise(extract).includes(normalisedPhrase)) {
      score += 8;
    }
  }

  if (title && factText.includes(normalise(title).trim())) {
    score += 14;
  }

  if (isGenericArticleTitle(title, placeTitle)) {
    score -= 18;
  }

  return score;
}

function searchQueries(fact: HistoryFact, placeTitle: string) {
  const factText = `${fact.title} ${fact.text}`;
  const names = namedPhrases(factText, placeTitle).slice(0, 5);
  const keywords = [...terms(factText, terms(placeTitle))].slice(0, 8);
  const titleKeywords = [...terms(fact.title, terms(placeTitle))].slice(0, 6);

  return Array.from(
    new Set([
      ...names,
      fact.title,
      titleKeywords.join(" "),
      keywords.slice(0, 6).join(" "),
      keywords.slice(0, 4).join(" "),
    ].map((query) => query.trim()).filter((query) => query.length > 3)),
  ).slice(0, 7);
}

async function fetchPageCandidates(query: string) {
  const params = new URLSearchParams({
    action: "query",
    format: "json",
    generator: "search",
    gsrsearch: query,
    gsrlimit: "8",
    prop: "pageimages|extracts|info",
    piprop: "original|thumbnail",
    pithumbsize: "960",
    exintro: "1",
    explaintext: "1",
    exsentences: "3",
    inprop: "url",
    origin: "*",
  });
  const response = await fetch(`https://en.wikipedia.org/w/api.php?${params}`);
  if (!response.ok) {
    return [];
  }
  const payload = await response.json();
  const pages = payload?.query?.pages;
  if (!pages || typeof pages !== "object") {
    return [];
  }
  return Object.values(pages) as WikiPage[];
}

async function searchFactArticleImage(fact: HistoryFact, placeTitle: string) {
  let best: ImageCandidate | null = null;

  for (const query of searchQueries(fact, placeTitle)) {
    const pages = await fetchPageCandidates(query);
    for (const page of pages) {
      const title = String(page.title ?? "").trim();
      if (!title) {
        continue;
      }
      const imageUrl = bestPageImage(page);
      if (!imageUrl) {
        continue;
      }
      const score = scorePage(fact, page, placeTitle);
      if (score < 12) {
        continue;
      }
      const image: HistoryLocationImage = {
        url: imageUrl,
        title,
        sourceName: "Wikipedia",
        sourceUrl: String(page.fullurl ?? articleUrl(title)),
      };
      if (!best || score > best.score) {
        best = { image, score };
      }
    }
    if (best && best.score >= 28) {
      break;
    }
  }

  return best?.image ?? null;
}

export function FactCardImage({
  fact,
  fallbackImage: _fallbackImage,
  placeTitle,
}: {
  fact: HistoryFact;
  fallbackImage: HistoryLocationImage | null;
  placeTitle: string;
}) {
  const [image, setImage] = useState<HistoryLocationImage | null>(null);
  const [failed, setFailed] = useState(false);
  const key = useMemo(() => `${placeTitle}|${fact.title}|${fact.text}`, [fact.text, fact.title, placeTitle]);

  useEffect(() => {
    let active = true;
    setImage(null);
    setFailed(false);

    void searchFactArticleImage(fact, placeTitle)
      .then((nextImage) => {
        if (active) {
          setImage(nextImage);
        }
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [fact, key, placeTitle]);

  if (!image || failed) {
    return null;
  }

  return (
    <div className="relative h-24 overflow-hidden">
      <img
        key={image.url}
        src={image.url}
        alt={`Image for ${fact.title}`}
        loading="lazy"
        onError={() => setFailed(true)}
        className="h-full w-full object-cover"
      />
      <div className="absolute inset-0 bg-gradient-to-r from-slate-950/35 via-slate-950/5 to-transparent" />
    </div>
  );
}
