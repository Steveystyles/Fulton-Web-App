import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { api, type NewsItem } from "../lib/api";
import { cleanNewsTitle } from "../lib/news";

const emptyHeadline = "No breaking Saints stories yet. The live feed is ready.";
const minimumTickerSlots = 5;

function mergeTickerItems(currentItems: NewsItem[], nextItems: NewsItem[]) {
  const itemsByKey = new Map<string, NewsItem>();

  for (const item of [...nextItems, ...currentItems]) {
    itemsByKey.set(item.sourceKey, item);
  }

  return Array.from(itemsByKey.values())
    .sort((left, right) => right.publishedAt.localeCompare(left.publishedAt))
    .slice(0, 12);
}

export function NewsTicker() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const tickerGroupRef = useRef<HTMLDivElement | null>(null);
  const [tickerShift, setTickerShift] = useState("-50%");

  useEffect(() => {
    let active = true;
    let stream: EventSource | null = null;
    let pollTimer: number | undefined;

    async function loadHeadlines(force = false) {
      try {
        const response = await api.news(12, "breaking", { force });
        if (active) {
          setItems((currentItems) => mergeTickerItems(currentItems, response.items));
        }
      } catch {
        if (active) {
          setItems((currentItems) => currentItems);
        }
      }
    }

    void loadHeadlines();
    pollTimer = window.setInterval(() => void loadHeadlines(true), 60_000);

    try {
      stream = new EventSource("/api/news/stream");
      stream.addEventListener("news", (event) => {
        if (!active) {
          return;
        }
        const item = JSON.parse((event as MessageEvent<string>).data) as NewsItem;
        if (item.priority === "breaking") {
          setItems((currentItems) => mergeTickerItems(currentItems, [item]));
        }
      });
      stream.onerror = () => {
        stream?.close();
        stream = null;
      };
    } catch {
      stream = null;
    }

    return () => {
      active = false;
      stream?.close();
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
      }
    };
  }, []);

  const headlines = useMemo(() => {
    if (items.length === 0) {
      return [emptyHeadline];
    }
    return items.map((item) => cleanNewsTitle(item.title, item.source));
  }, [items]);
  const tickerHeadlines = useMemo(() => {
    const repetitions = Math.max(1, Math.ceil(minimumTickerSlots / headlines.length));
    return Array.from({ length: repetitions }, () => headlines).flat();
  }, [headlines]);

  useEffect(() => {
    const group = tickerGroupRef.current;
    if (!group) {
      return undefined;
    }

    function updateTickerShift() {
      const width = Math.ceil(group.getBoundingClientRect().width);
      if (width > 0) {
        setTickerShift(`-${width}px`);
      }
    }

    updateTickerShift();
    window.setTimeout(updateTickerShift, 250);

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateTickerShift);
      return () => window.removeEventListener("resize", updateTickerShift);
    }

    const observer = new ResizeObserver(updateTickerShift);
    observer.observe(group);
    return () => observer.disconnect();
  }, [tickerHeadlines]);

  const tickerLabel = "Breaking";

  return (
    <section
      className="ticker-frame border-b border-white/10 bg-saints-charcoal text-white"
      aria-label="News ticker"
      style={{ "--ticker-shift": tickerShift } as CSSProperties}
    >
      <div className="flex min-h-10 items-center gap-3 overflow-hidden pl-4">
        <span className="inline-flex items-center gap-1.5 rounded-sm bg-saints-red px-2.5 py-1 text-xs font-black uppercase leading-none text-white">
          <span className="h-1.5 w-1.5 rounded-full bg-white" aria-hidden="true" />
          {tickerLabel}
        </span>
        <div className="min-w-0 flex-1 overflow-hidden saints-focus" tabIndex={0}>
          <div className="ticker-track flex w-max min-w-full items-center whitespace-nowrap text-sm font-semibold text-white/[0.88]">
            {[0, 1].map((groupIndex) => (
              <div
                key={groupIndex}
                ref={groupIndex === 0 ? tickerGroupRef : undefined}
                className="ticker-group flex min-w-full shrink-0 items-center gap-8 pr-8"
                aria-hidden={groupIndex > 0}
              >
                {tickerHeadlines.map((headline, index) => (
                  <span key={`${groupIndex}-${headline}-${index}`}>{headline}</span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
