import {
  ArrowDownUp,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Newspaper,
  SlidersHorizontal,
  Trophy,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { api, type NewsCategory, type NewsItem } from "../lib/api";
import {
  cleanNewsSummary,
  cleanNewsTitle,
  newsFallbackRefreshMs,
  newsStoryKey,
  visibleNewsTags,
} from "../lib/news";

type FeedStatus = "loading" | "live" | "polling" | "offline";
type NewsOrder = "newest" | "oldest";

const categoryOptions: Array<{ value: NewsCategory; label: string }> = [
  { value: "all", label: "All" },
  { value: "breaking", label: "Breaking" },
  { value: "live-scores", label: "Live scores" },
  { value: "news", label: "News" },
];

function mergeItems(currentItems: NewsItem[], nextItems: NewsItem[]) {
  const itemsByKey = new Map<string, NewsItem>();

  for (const item of [...nextItems, ...currentItems]) {
    itemsByKey.set(newsStoryKey(item.title, item.source), item);
  }

  return Array.from(itemsByKey.values()).sort((left, right) => {
    return right.publishedAt.localeCompare(left.publishedAt);
  });
}

function formatPublishedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Latest";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatPriority(priority: string) {
  if (priority === "live-scores") {
    return "Live scores";
  }
  if (priority === "breaking") {
    return "Breaking";
  }
  return "News";
}

function priorityClass(priority: string) {
  if (priority === "breaking") {
    return "bg-saints-red text-white";
  }
  if (priority === "live-scores") {
    return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  }
  return "bg-slate-100 text-slate-700 ring-1 ring-slate-200";
}

function shouldShowItem(item: NewsItem, category: NewsCategory) {
  return category === "all" || item.priority === category;
}

export function News() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [category, setCategory] = useState<NewsCategory>("all");
  const [order, setOrder] = useState<NewsOrder>("newest");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [status, setStatus] = useState<FeedStatus>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let stream: EventSource | null = null;
    let pollTimer: number | undefined;

    setItems([]);
    setStatus("loading");
    setError("");

    async function loadLatest(nextStatus: FeedStatus, force = false) {
      try {
        const response = await api.news(50, category, { force });
        if (active) {
          setItems((currentItems) => mergeItems(currentItems, response.items));
          setStatus(nextStatus);
          setError("");
        }
      } catch (caughtError) {
        if (active) {
          setStatus("offline");
          setError(caughtError instanceof Error ? caughtError.message : "News failed to load.");
        }
      }
    }

    function refreshWhenVisible() {
      if (document.visibilityState === "visible") {
        void loadLatest("live", true);
      }
    }

    void loadLatest("live", true);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    try {
      stream = new EventSource("/api/news/stream");
      stream.addEventListener("ready", () => {
        if (active) {
          setStatus("live");
        }
      });
      stream.addEventListener("news", (event) => {
        if (!active) {
          return;
        }
        const item = JSON.parse((event as MessageEvent<string>).data) as NewsItem;
        if (shouldShowItem(item, category)) {
          setItems((currentItems) => mergeItems(currentItems, [item]));
        }
        setStatus("live");
      });
      stream.onerror = () => {
        stream?.close();
        stream = null;
        if (active) {
          setStatus("polling");
          pollTimer = window.setInterval(() => void loadLatest("polling", true), newsFallbackRefreshMs);
        }
      };
    } catch {
      setStatus("polling");
      pollTimer = window.setInterval(() => void loadLatest("polling", true), newsFallbackRefreshMs);
    }

    return () => {
      active = false;
      stream?.close();
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
      }
    };
  }, [category]);

  const statusLabel = useMemo(() => {
    if (status === "loading") {
      return "Loading";
    }
    if (status === "live") {
      return "Live";
    }
    if (status === "polling") {
      return "Polling";
    }
    return "Offline";
  }, [status]);

  const selectedCategoryLabel = useMemo(() => {
    return categoryOptions.find((option) => option.value === category)?.label ?? "All";
  }, [category]);
  const emptyStoryLabel =
    category === "all" ? "stories" : `${selectedCategoryLabel.toLowerCase()} stories`;
  const orderedItems = useMemo(() => {
    return [...items].sort((left, right) => {
      const comparison = right.publishedAt.localeCompare(left.publishedAt);
      return order === "newest" ? comparison : -comparison;
    });
  }, [items, order]);

  return (
    <section className="page-fade space-y-3" aria-label="News">
      <div className="flex items-center justify-end gap-2">
        <span
          className={[
            "inline-flex min-h-8 items-center gap-1 rounded-full px-2.5 py-1 text-[0.68rem] font-black uppercase tracking-normal",
            status === "live"
              ? "bg-emerald-50 text-emerald-700"
              : status === "offline"
                ? "bg-red-50 text-saints-red"
                : "bg-slate-100 text-slate-600",
          ].join(" ")}
        >
          {status === "loading" ? (
            <LoaderCircle aria-hidden="true" className="h-3 w-3 animate-spin" />
          ) : null}
          {statusLabel}
        </span>
        <button
          type="button"
          onClick={() => setFiltersOpen((current) => !current)}
          aria-expanded={filtersOpen}
          className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs font-black text-slate-950 transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
        >
          <SlidersHorizontal aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
          Filter
        </button>
      </div>

      {filtersOpen ? (
        <Card className="p-3" as="section" aria-label="News filters">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block min-w-0">
              <span className="text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                Stories
              </span>
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value as NewsCategory)}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm font-black text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              >
                {categoryOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block min-w-0">
              <span className="inline-flex items-center gap-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                <ArrowDownUp aria-hidden="true" className="h-3 w-3" strokeWidth={2.6} />
                Order
              </span>
              <select
                value={order}
                onChange={(event) => setOrder(event.target.value as NewsOrder)}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm font-black text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>
          </div>
        </Card>
      ) : null}

      {error ? (
        <Card>
          <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
            {error}
          </p>
        </Card>
      ) : null}

      {items.length === 0 && status !== "loading" ? (
        <Card>
          <div className="flex items-start gap-3">
            <Newspaper
              aria-hidden="true"
              className="mt-1 h-6 w-6 shrink-0 text-saints-red"
              strokeWidth={2.4}
            />
            <div>
              <p className="text-lg font-black text-slate-950">
                No {emptyStoryLabel} yet
              </p>
              <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-600">
                New stories will appear here as the app news monitor finds them.
              </p>
            </div>
          </div>
        </Card>
      ) : null}

      <section className="space-y-3" aria-label="Latest news stories">
        {orderedItems.map((item) => {
          const title = cleanNewsTitle(item.title, item.source);
          const summary = cleanNewsSummary(item.summary, title, item.source);
          const tags = visibleNewsTags(item.tags);

          return (
            <Card
              key={newsStoryKey(title, item.source)}
              as="article"
              className="rounded-[1.35rem] p-0"
            >
              <div className="border-l-4 border-saints-red">
                <div className="p-4 sm:p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[0.68rem] font-black uppercase tracking-wide text-slate-500">
                        {item.source}
                      </p>
                      <p className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-500">
                        <Clock3 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.4} />
                        {formatPublishedAt(item.publishedAt)}
                      </p>
                    </div>
                    <span
                      className={[
                        "inline-flex min-h-7 shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[0.68rem] font-black uppercase tracking-wide",
                        priorityClass(item.priority),
                      ].join(" ")}
                    >
                      {item.priority === "live-scores" ? (
                        <Trophy aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
                      ) : null}
                      {formatPriority(item.priority)}
                    </span>
                  </div>

                  <h3 className="mt-4 text-lg font-black leading-snug text-slate-950">
                    {title}
                  </h3>

                  {summary ? (
                    <p className="mt-2.5 text-[0.95rem] font-medium leading-6 text-slate-600">
                      {summary}
                    </p>
                  ) : null}
                </div>

                <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50/80 px-4 py-3 sm:px-5">
                  {tags.length > 0 ? (
                    <div className="flex flex-wrap gap-2" aria-label="Story tags">
                      {tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full bg-white px-2.5 py-1 text-[0.68rem] font-black uppercase tracking-wide text-slate-600 ring-1 ring-slate-200"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Read story from ${item.source}: ${title}`}
                    className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-saints-charcoal focus:outline-none focus:ring-4 focus:ring-saints-red/20 sm:w-auto sm:self-start"
                  >
                    Read story
                    <ExternalLink aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                  </a>
                </div>
              </div>
            </Card>
          );
        })}
      </section>
    </section>
  );
}
