import { useEffect, useMemo, useState } from "react";
import { type HistoryFact, type HistoryLocationImage } from "../lib/api";

async function resolveFactImage(fact: HistoryFact, placeTitle: string) {
  const response = await fetch("/api/fact-image", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: fact.title,
      text: fact.text,
      placeTitle,
    }),
  });

  if (!response.ok) {
    return null;
  }

  const image = await response.json() as HistoryLocationImage;
  return image?.url ? image : null;
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
  const lookupKey = useMemo(
    () => `${placeTitle}|${fact.title}|${fact.text}`,
    [fact.text, fact.title, placeTitle],
  );

  useEffect(() => {
    let active = true;
    setImage(null);
    setFailed(false);

    void resolveFactImage(fact, placeTitle)
      .then((nextImage) => {
        if (active) {
          setImage(nextImage);
        }
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [fact, lookupKey, placeTitle]);

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
