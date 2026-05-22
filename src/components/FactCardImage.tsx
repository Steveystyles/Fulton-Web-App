import { useEffect, useMemo, useState } from "react";
import { type HistoryFact, type HistoryLocationImage } from "../lib/api";

const factImageStopTerms = new Set([
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

function imageScore(fact: HistoryFact, image: HistoryLocationImage, placeTitle: string) {
  const placeTerms = textTerms(placeTitle);
  const factTerms = textTerms(`${fact.title} ${fact.text}`, placeTerms);
  const imageTerms = textTerms(image.title, placeTerms);
  let score = 0;
  for (const term of factTerms) {
    if (imageTerms.has(term)) {
      score += 12;
    }
  }

  const titleLower = image.title.toLowerCase();
  const factLower = fact.text.toLowerCase();
  if ([...factTerms].some((term) => titleLower.includes(term) && factLower.includes(term))) {
    score += 6;
  }
  return score;
}

function existingImageIsRelevant(
  fact: HistoryFact,
  image: HistoryLocationImage | null,
  placeTitle: string,
) {
  if (!image) {
    return false;
  }
  return imageScore(fact, image, placeTitle) >= 12;
}

function factImageQueries(fact: HistoryFact, placeTitle: string) {
  const placeName = placeTitle.split(",", 1)[0].trim();
  const placeTerms = textTerms(placeTitle);
  const factText = `${fact.title} ${fact.text}`;
  const namedTerms = properTerms(factText, placeTerms);
  const fallbackTerms = [...textTerms(factText, placeTerms)].slice(0, 5);
  const groups = [
    namedTerms.slice(0, 4),
    namedTerms.slice(0, 2),
    fallbackTerms.slice(0, 4),
    fallbackTerms.slice(0, 2),
  ].filter((group) => group.length > 0);

  return Array.from(
    new Set(
      groups.map((group) => [placeName, ...group].filter(Boolean).join(" ")),
    ),
  ).slice(0, 4);
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

export function FactCardImage({
  fact,
  fallbackImage,
  placeTitle,
}: {
  fact: HistoryFact;
  fallbackImage: HistoryLocationImage | null;
  placeTitle: string;
}) {
  const [resolvedImage, setResolvedImage] = useState<HistoryLocationImage | null>(fallbackImage);
  const [imageFailed, setImageFailed] = useState(false);
  const lookupKey = useMemo(
    () => `${placeTitle}|${fact.title}|${fact.text}|${fallbackImage?.url ?? ""}`,
    [fact.text, fact.title, fallbackImage?.url, placeTitle],
  );

  useEffect(() => {
    let active = true;
    setImageFailed(false);
    setResolvedImage(fallbackImage);

    if (existingImageIsRelevant(fact, fallbackImage, placeTitle)) {
      return () => {
        active = false;
      };
    }

    void searchCommonsImage(fact, placeTitle)
      .then((image) => {
        if (active && image) {
          setResolvedImage(image);
        }
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [fact, fallbackImage, lookupKey, placeTitle]);

  if (!resolvedImage || imageFailed) {
    return null;
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
