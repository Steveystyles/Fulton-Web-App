import { useEffect, useMemo, useState } from "react";
import { type HistoryFact, type HistoryLocationImage } from "../lib/api";

const factImageStopTerms = new Set([
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
  "image",
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

const rejectedImageTerms = [
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

type CommonsPage = {
  title?: string;
  imageinfo?: Array<{
    thumburl?: string;
    url?: string;
    descriptionurl?: string;
  }>;
};

type WikipediaSearchPage = {
  title?: string;
  description?: string;
  excerpt?: string;
  thumbnail?: {
    url?: string;
  };
};

function absoluteWikipediaImageUrl(url: string | undefined) {
  if (!url) {
    return null;
  }
  if (url.startsWith("//")) {
    return `https:${url}`;
  }
  if (url.startsWith("/")) {
    return `https://en.wikipedia.org${url}`;
  }
  return url.startsWith("https://") ? url : null;
}

function wikipediaArticleUrl(title: string) {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
}

function textTerms(value: string, excludedTerms = new Set<string>()) {
  const terms = new Set<string>();
  for (const match of value.matchAll(/[A-Za-z][A-Za-z0-9']+/g)) {
    const term = match[0].toLowerCase();
    if (term.length < 4 || factImageStopTerms.has(term) || excludedTerms.has(term)) {
      continue;
    }
    terms.add(term);
  }
  return terms;
}

function properTerms(value: string, excludedTerms: Set<string>) {
  const terms: string[] = [];
  const seen = new Set<string>();
  for (const match of value.matchAll(/[A-Z][A-Za-z0-9']+/g)) {
    const rawTerm = match[0];
    const term = rawTerm.toLowerCase();
    if (
      rawTerm.length < 4 ||
      seen.has(term) ||
      excludedTerms.has(term) ||
      factImageStopTerms.has(term)
    ) {
      continue;
    }
    terms.push(rawTerm);
    seen.add(term);
  }
  return terms;
}

function imageFromCommonsPage(page: CommonsPage): HistoryLocationImage | null {
  const title = String(page.title ?? "");
  const cleanTitle = title.replace(/^File:/i, "").trim();
  const titleLower = cleanTitle.toLowerCase();
  if (!/\.(?:jpe?g|png|webp)$/i.test(cleanTitle)) {
    return null;
  }
  if (rejectedImageTerms.some((term) => titleLower.includes(term))) {
    return null;
  }

  const info = page.imageinfo?.[0];
  const url = info?.thumburl ?? info?.url;
  if (!url?.startsWith("https://")) {
    return null;
  }

  return {
    url,
    title: cleanTitle,
    sourceName: "Wikimedia Commons",
    sourceUrl: info?.descriptionurl ?? null,
  };
}

function pageTextScore(fact: HistoryFact, pageText: string, placeTitle: string) {
  const placeTerms = textTerms(placeTitle);
  const factTerms = textTerms(`${fact.title} ${fact.text}`, placeTerms);
  const pageTerms = textTerms(pageText, placeTerms);
  let score = 0;
  for (const term of factTerms) {
    if (pageTerms.has(term)) {
      score += 10;
    }
  }
  return score;
}

function imageScore(fact: HistoryFact, image: HistoryLocationImage, placeTitle: string) {
  const titleScore = pageTextScore(fact, image.title, placeTitle);
  const titleLower = image.title.toLowerCase();
  const factLower = fact.text.toLowerCase();
  const placeTerms = textTerms(placeTitle);
  const factTerms = textTerms(`${fact.title} ${fact.text}`, placeTerms);
  const bonus = [...factTerms].some((term) => titleLower.includes(term) && factLower.includes(term)) ? 6 : 0;
  return titleScore + bonus;
}

function factImageQueries(fact: HistoryFact, placeTitle: string) {
  const placeName = placeTitle.split(",", 1)[0].trim();
  const placeTerms = textTerms(placeTitle);
  const factText = `${fact.title} ${fact.text}`;
  const namedTerms = properTerms(factText, placeTerms);
  const fallbackTerms = [...textTerms(factText, placeTerms)].slice(0, 6);
  const groups = [
    namedTerms.slice(0, 5),
    namedTerms.slice(0, 3),
    fallbackTerms.slice(0, 5),
    fallbackTerms.slice(0, 3),
    fallbackTerms.slice(0, 2),
  ].filter((group) => group.length > 0);

  return Array.from(
    new Set(
      groups.map((group) => [placeName, ...group].filter(Boolean).join(" ")),
    ),
  ).slice(0, 5);
}

function wikipediaPageToImage(
  fact: HistoryFact,
  page: WikipediaSearchPage,
  placeTitle: string,
): { image: HistoryLocationImage; score: number } | null {
  const title = String(page.title ?? "").trim();
  const thumbnailUrl = absoluteWikipediaImageUrl(page.thumbnail?.url);
  if (!title || !thumbnailUrl) {
    return null;
  }
  const titleLower = title.toLowerCase();
  if (rejectedImageTerms.some((term) => titleLower.includes(term))) {
    return null;
  }
  const searchableText = `${title} ${page.description ?? ""} ${page.excerpt ?? ""}`;
  const score = pageTextScore(fact, searchableText, placeTitle);
  if (score <= 0) {
    return null;
  }
  return {
    score,
    image: {
      url: thumbnailUrl,
      title,
      sourceName: "Wikipedia",
      sourceUrl: wikipediaArticleUrl(title),
    },
  };
}

async function searchWikipediaFactArticleImage(fact: HistoryFact, placeTitle: string) {
  const queries = factImageQueries(fact, placeTitle);
  let best: { image: HistoryLocationImage; score: number } | null = null;

  for (const query of queries) {
    const params = new URLSearchParams({ q: query, limit: "8" });
    const response = await fetch(`https://en.wikipedia.org/w/rest.php/v1/search/page?${params}`);
    if (!response.ok) {
      continue;
    }
    const payload = await response.json();
    const pages = Array.isArray(payload?.pages) ? payload.pages : [];
    for (const page of pages as WikipediaSearchPage[]) {
      const candidate = wikipediaPageToImage(fact, page, placeTitle);
      if (candidate && (!best || candidate.score > best.score)) {
        best = candidate;
      }
    }
    if (best && best.score >= 20) {
      break;
    }
  }

  return best?.image ?? null;
}

async function searchCommonsImage(fact: HistoryFact, placeTitle: string) {
  const queries = factImageQueries(fact, placeTitle);
  const placeTerms = textTerms(placeTitle);
  let best: { image: HistoryLocationImage; score: number } | null = null;

  for (const query of queries) {
    const params = new URLSearchParams({
      action: "query",
      format: "json",
      generator: "search",
      gsrnamespace: "6",
      gsrlimit: "8",
      gsrsearch: query,
      prop: "imageinfo",
      iiprop: "url",
      iiurlwidth: "960",
      origin: "*",
    });
    const response = await fetch(`https://commons.wikimedia.org/w/api.php?${params}`);
    if (!response.ok) {
      continue;
    }
    const payload = await response.json();
    const pages = payload?.query?.pages;
    if (!pages || typeof pages !== "object") {
      continue;
    }

    for (const page of Object.values(pages) as CommonsPage[]) {
      const image = imageFromCommonsPage(page);
      if (!image) {
        continue;
      }
      const score = imageScore(fact, image, placeTitle) + (textTerms(image.title, placeTerms).size > 0 ? 2 : 0);
      if (score > 0 && (!best || score > best.score)) {
        best = { image, score };
      }
    }

    if (best && best.score >= 18) {
      break;
    }
  }

  return best?.image ?? null;
}

async function searchFactImage(fact: HistoryFact, placeTitle: string) {
  const articleImage = await searchWikipediaFactArticleImage(fact, placeTitle);
  if (articleImage) {
    return articleImage;
  }
  return searchCommonsImage(fact, placeTitle);
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
  const [resolvedImage, setResolvedImage] = useState<HistoryLocationImage | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [searching, setSearching] = useState(true);
  const lookupKey = useMemo(
    () => `${placeTitle}|${fact.title}|${fact.text}`,
    [fact.text, fact.title, placeTitle],
  );

  useEffect(() => {
    let active = true;
    setImageFailed(false);
    setResolvedImage(null);
    setSearching(true);

    void searchFactImage(fact, placeTitle)
      .then((image) => {
        if (active && image) {
          setResolvedImage(image);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) {
          setSearching(false);
        }
      });

    return () => {
      active = false;
    };
  }, [fact, lookupKey, placeTitle]);

  if (!resolvedImage || imageFailed) {
    return searching ? (
      <div className="h-24 animate-pulse bg-slate-100" aria-label="Finding article image" />
    ) : null;
  }

  return (
    <div className="relative h-24 overflow-hidden">
      <img
        key={resolvedImage.url}
        src={resolvedImage.url}
        alt=""
        loading="lazy"
        onError={() => setImageFailed(true)}
        className="h-full w-full object-cover"
      />
      <div className="absolute inset-0 bg-gradient-to-r from-slate-950/35 via-slate-950/5 to-transparent" />
    </div>
  );
}
