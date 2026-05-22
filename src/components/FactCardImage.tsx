import { useEffect, useMemo, useState } from "react";
import { type HistoryFact, type HistoryLocationImage } from "../lib/api";

type WikiSearchPage = {
  title?: string;
  description?: string;
  excerpt?: string;
};

type WikiSummary = {
  title?: string;
  description?: string;
  extract?: string;
  thumbnail?: { source?: string; width?: number; height?: number };
  originalimage?: { source?: string; width?: number; height?: number };
  content_urls?: { desktop?: { page?: string } };
};

const stopWords = new Set([
  "about",
  "after",
  "among",
  "annual",
  "based",
  "became",
  "been",
  "before",
  "building",
  "buildings",
  "centre",
  "century",
  "during",
  "fact",
  "facts",
  "first",
  "former",
  "from",
  "history",
  "into",
  "late",
  "local",
  "many",
  "most",
  "name",
  "named",
  "that",
  "their",
  "this",
  "today",
  "town",
  "used",
  "were",
  "which",
  "with",
]);

const genericImageWords = [
  "arms",
  "badge",
  "coat",
  "diagram",
  "flag",
  "icon",
  "locator",
  "logo",
  "map",
  "seal",
  "shield",
  "symbol",
];

function terms(text: string, excluded = new Set<string>()) {
  const output = new Set<string>();
  for (const match of text.matchAll(/[A-Za-z][A-Za-z0-9']+/g)) {
    const term = match[0].toLowerCase();
    if (term.length >= 4 && !stopWords.has(term) && !excluded.has(term)) {
      output.add(term);
    }
  }
  return output;
}

function namedPhrases(text: string, placeTitle: string) {
  const place = placeTitle.split(",", 1)[0].trim().toLowerCase();
  const seen = new Set<string>();
  const output: string[] = [];
  for (const match of text.matchAll(/[A-Z][A-Za-z0-9']+(?:\s+[A-Z][A-Za-z0-9']+)*/g)) {
    const phrase = match[0].trim();
    const key = phrase.toLowerCase();
    if (phrase.length >= 4 && key !== place && !seen.has(key) && !stopWords.has(key)) {
      seen.add(key);
      output.push(phrase);
    }
  }
  return output;
}

function scoreFactMatch(fact: HistoryFact, pageText: string, placeTitle: string) {
  const placeTerms = terms(placeTitle);
  const factTerms = terms(`${fact.title} ${fact.text}`, placeTerms);
  const pageTerms = terms(pageText, placeTerms);
  let score = 0;
  for (const term of factTerms) {
    if (pageTerms.has(term)) {
      score += 1;
    }
  }
  return score;
}

function articleUrl(title: string) {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
}

function isGenericImage(url: string) {
  const normalised = decodeURIComponent(url).toLowerCase();
  return genericImageWords.some((word) => normalised.includes(word));
}

function bestSummaryImage(summary: WikiSummary) {
  const original = summary.originalimage;
  if (original?.source?.startsWith("https://") && !isGenericImage(original.source)) {
    if ((original.width ?? 0) >= 320 && (original.height ?? 0) >= 160) {
      return original.source;
    }
  }

  const thumbnail = summary.thumbnail;
  if (thumbnail?.source?.startsWith("https://") && !isGenericImage(thumbnail.source)) {
    if ((thumbnail.width ?? 0) >= 240 && (thumbnail.height ?? 0) >= 120) {
      return thumbnail.source;
    }
  }

  return null;
}

function searchQueries(fact: HistoryFact, placeTitle: string) {
  const place = placeTitle.split(",", 1)[0].trim();
  const factText = `${fact.title} ${fact.text}`;
  const names = namedPhrases(factText, placeTitle).slice(0, 3);
  const keywords = [...terms(factText, terms(placeTitle))].slice(0, 5);
  return Array.from(
    new Set([
      ...names.map((name) => `${place} ${name}`),
      ...names,
      `${place} ${keywords.slice(0, 4).join(" ")}`,
      keywords.slice(0, 4).join(" "),
    ].filter((query) => query.trim().length > 3)),
  ).slice(0, 6);
}

async function fetchSummary(title: string) {
  const response = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}?redirect=true`);
  if (!response.ok) {
    return null;
  }
  return response.json() as Promise<WikiSummary>;
}

async function searchFactArticleImage(fact: HistoryFact, placeTitle: string) {
  let best: { image: HistoryLocationImage; score: number } | null = null;

  for (const query of searchQueries(fact, placeTitle)) {
    const params = new URLSearchParams({ q: query, limit: "8" });
    const searchResponse = await fetch(`https://en.wikipedia.org/w/rest.php/v1/search/page?${params}`);
    if (!searchResponse.ok) {
      continue;
    }
    const searchPayload = await searchResponse.json();
    const pages = Array.isArray(searchPayload?.pages) ? searchPayload.pages : [];

    for (const page of pages as WikiSearchPage[]) {
      const title = String(page.title ?? "").trim();
      if (!title || genericImageWords.some((word) => title.toLowerCase().includes(word))) {
        continue;
      }
      const searchScore = scoreFactMatch(fact, `${title} ${page.description ?? ""} ${page.excerpt ?? ""}`, placeTitle);
      if (searchScore < 2) {
        continue;
      }

      const summary = await fetchSummary(title);
      if (!summary) {
        continue;
      }
      const imageUrl = bestSummaryImage(summary);
      if (!imageUrl) {
        continue;
      }
      const summaryScore = scoreFactMatch(fact, `${summary.title ?? title} ${summary.description ?? ""} ${summary.extract ?? ""}`, placeTitle);
      const score = searchScore + summaryScore;
      if (score < 4) {
        continue;
      }

      const image: HistoryLocationImage = {
        url: imageUrl,
        title: String(summary.title ?? title),
        sourceName: "Wikipedia",
        sourceUrl: summary.content_urls?.desktop?.page ?? articleUrl(title),
      };
      if (!best || score > best.score) {
        best = { image, score };
      }
    }

    if (best && best.score >= 7) {
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

    const timer = window.setTimeout(() => {
      void searchFactArticleImage(fact, placeTitle)
        .then((nextImage) => {
          if (active) {
            setImage(nextImage);
          }
        })
        .catch(() => undefined);
    }, 250);

    return () => {
      active = false;
      window.clearTimeout(timer);
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
