import {
  ExternalLink,
  LoaderCircle,
  Newspaper,
  Radio,
  Trophy,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { api, type NewsCategory, type NewsItem } from "../lib/api";
import { cleanNewsTitle } from "../lib/news";

type FeedStatus = "loading" | "live" | "polling" | "offline";

const categoryOptions: Array<{ value: NewsCategory; label: string }> = [
  { value: "all", label: "All" },
  { value: "breaking", label: "Breaking" },
  { value: "live-scores", label: "Live scores" },
  { value: "news", label: "News" },
];

function mergeItems(currentItems: NewsItem[], nextItems: NewsItem[]) {
  const itemsByKey = new Map<string, NewsItem>();

  for (const item of [...nextItems, ...currentItems]) {
    itemsByKey.set(item.sourceKey, item);
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

function shouldShowItem(item: NewsItem, category: NewsCategory) {
  return category === "all" || item.priority === category;
}

export function News() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [category, setCategory] = useState<NewsCategory>("all");
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

    void loadLatest("live");

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
          pollTimer = window.setInterval(() => void loadLatest("polling", true), 60_000);
        }
      };
    } catch {
      setStatus("polling");
      pollTimer = window.setInterval(() => void loadLatest("polling", true), 60_000);
    }

    return () => {
      active = false;
      stream?.close();
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

  return (
    <section className="page-fade space-y-3" aria-label="News">
      <Card className="p-3">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
              {status === "loading" ? (
                <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin" />
              ) : (
                <Radio aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-lg font-black leading-tight text-slate-950">
                St Mirren feed
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-600">
                {selectedCategoryLabel} - {statusLabel}
              </p>
            </div>
            <span
              className={[
                "rounded-full px-3 py-1 text-xs font-black uppercase",
                status === "live"
                  ? "bg-emerald-50 text-emerald-700"
                  : status === "offline"
                    ? "bg-red-50 text-saints-red"
                    : "bg-slate-100 text-slate-600",
              ].join(" ")}
            >
              {statusLabel}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2" aria-label="News filters">
            {categoryOptions.map((option) => {
              const active = option.value === category;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setCategory(option.value)}
                  className={[
                    "flex min-h-11 items-center justify-center rounded-xl border px-2 text-sm font-black transition focus:outline-none focus:ring-4 focus:ring-saints-red/20",
                    active
                      ? "border-saints-black bg-saints-black text-white"
                      : "border-saints-line bg-white text-slate-700 hover:border-saints-red/40 hover:bg-saints-redSoft",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              );
            })}
          </div>

          {error ? (
            <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
              {error}
            </p>
          ) : null}
        </div>
      </Card>

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
        {items.map((item) => {
          const title = cleanNewsTitle(item.title, item.source);

          return (
            <Card key={item.sourceKey} as="article" className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-lg font-black leading-tight text-slate-950">
                    {title}
                  </h3>
                  <p className="mt-2 text-xs font-black uppercase tracking-normal text-saints-red">
                    {item.source} - {formatPublishedAt(item.publishedAt)}
                  </p>
                </div>
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open story: ${title}`}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-mist text-slate-950 transition hover:bg-saints-red hover:text-white focus:outline-none focus:ring-4 focus:ring-saints-red/20"
                >
                  <ExternalLink aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                </a>
              </div>

              {item.summary ? (
                <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-600">
                  {item.summary}
                </p>
              ) : null}

              <div className="mt-3 flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1 rounded-full bg-saints-redSoft px-2.5 py-1 text-xs font-black uppercase text-saints-red">
                  {item.priority === "live-scores" ? (
                    <Trophy aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
                  ) : null}
                  {formatPriority(item.priority)}
                </span>
                {item.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-saints-mist px-2.5 py-1 text-xs font-black uppercase text-slate-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </Card>
          );
        })}
      </section>
    </section>
  );
}
