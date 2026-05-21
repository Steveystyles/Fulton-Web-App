import { useEffect, useMemo, useState } from "react";
import { api, type NewsItem } from "../lib/api";
import { cleanNewsTitle } from "../lib/news";

const emptyHeadline = "No breaking Saints stories yet. The live feed is ready.";

export function NewsTicker() {
  const [items, setItems] = useState<NewsItem[]>([]);

  useEffect(() => {
    let active = true;

    async function loadHeadlines() {
      try {
        const response = await api.news(5, "breaking");
        const fallbackResponse =
          response.items.length === 0 ? await api.news(5, "all") : response;
        if (active) {
          setItems(fallbackResponse.items);
        }
      } catch {
        if (active) {
          setItems([]);
        }
      }
    }

    void loadHeadlines();

    return () => {
      active = false;
    };
  }, []);

  const headline = useMemo(() => {
    if (items.length === 0) {
      return emptyHeadline;
    }
    return items.map((item) => cleanNewsTitle(item.title, item.source)).join("   |   ");
  }, [items]);
  const tickerLabel = useMemo(() => {
    if (items.some((item) => item.priority === "live-scores")) {
      return "Live";
    }
    if (items.length > 0 && items.every((item) => item.priority === "breaking")) {
      return "Breaking";
    }
    return "News";
  }, [items]);

  return (
    <section
      className="ticker-frame border-b border-white/10 bg-saints-charcoal text-white"
      aria-label="News ticker"
    >
      <div className="flex min-h-10 items-center gap-3 overflow-hidden pl-4">
        <span className="inline-flex items-center gap-1.5 rounded-sm bg-saints-red px-2.5 py-1 text-xs font-black uppercase leading-none text-white">
          <span className="h-1.5 w-1.5 rounded-full bg-white" aria-hidden="true" />
          {tickerLabel}
        </span>
        <div className="min-w-0 flex-1 overflow-hidden saints-focus" tabIndex={0}>
          <div className="ticker-track flex w-max items-center gap-8 whitespace-nowrap text-sm font-semibold text-white/[0.88]">
            <span>{headline}</span>
            <span aria-hidden="true">{headline}</span>
            <span aria-hidden="true">{headline}</span>
            <span aria-hidden="true">{headline}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
