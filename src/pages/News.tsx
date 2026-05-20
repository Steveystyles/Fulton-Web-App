import { ExternalLink, LoaderCircle, Newspaper, Radio } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";
import { api, type NewsItem } from "../lib/api";

type FeedStatus = "loading" | "live" | "polling" | "offline";

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

export function News() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [status, setStatus] = useState<FeedStatus>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let stream: EventSource | null = null;
    let pollTimer: number | undefined;

    async function loadLatest(nextStatus: FeedStatus) {
      try {
        const response = await api.news(50);
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
        setItems((currentItems) => mergeItems(currentItems, [item]));
        setStatus("live");
      });
      stream.onerror = () => {
        stream?.close();
        stream = null;
        if (active) {
          setStatus("polling");
          pollTimer = window.setInterval(() => void loadLatest("polling"), 60_000);
        }
      };
    } catch {
      setStatus("polling");
      pollTimer = window.setInterval(() => void loadLatest("polling"), 60_000);
    }

    return () => {
      active = false;
      stream?.close();
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
      }
    };
  }, []);

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

  return (
    <PageContainer title="NEWS" number="5">
      <Card>
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
            {status === "loading" ? (
              <LoaderCircle aria-hidden="true" className="h-6 w-6 animate-spin" />
            ) : (
              <Radio aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
            )}
          </div>
          <div className="min-w-0">
            <p className="text-xl font-black leading-tight text-slate-950">
              St Mirren news feed
            </p>
            <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-600">
              {statusLabel} delivery from the app news API.
            </p>
            {error ? (
              <p className="mt-2 rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
                {error}
              </p>
            ) : null}
          </div>
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
              <p className="text-lg font-black text-slate-950">No breaking stories yet</p>
              <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-600">
                New stories will appear here when the monitor posts them into the app.
              </p>
            </div>
          </div>
        </Card>
      ) : null}

      <section className="space-y-3" aria-label="Latest news stories">
        {items.map((item) => (
          <Card key={item.sourceKey} as="article" className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-black uppercase tracking-normal text-saints-red">
                  {item.source} · {formatPublishedAt(item.publishedAt)}
                </p>
                <h3 className="mt-2 text-lg font-black leading-tight text-slate-950">
                  {item.title}
                </h3>
              </div>
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                aria-label={`Open story: ${item.title}`}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-950 transition hover:bg-saints-red hover:text-white focus:outline-none focus:ring-4 focus:ring-saints-red/20"
              >
                <ExternalLink aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
              </a>
            </div>

            {item.summary ? (
              <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-600">
                {item.summary}
              </p>
            ) : null}

            {item.tags.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {item.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-black uppercase text-slate-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </Card>
        ))}
      </section>
    </PageContainer>
  );
}
