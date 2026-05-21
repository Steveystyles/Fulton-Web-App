import {
  BookOpen,
  CalendarDays,
  ExternalLink,
  LoaderCircle,
  MapPin,
  Search,
  Sparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type HistoryResponse } from "../lib/api";
import { Card } from "./Card";

const defaultLocation = "Paisley";

function todayIsoDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function HistoryKnowledge() {
  const [location, setLocation] = useState(defaultLocation);
  const [submittedLocation, setSubmittedLocation] = useState(defaultLocation);
  const [historyDate, setHistoryDate] = useState(todayIsoDate);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    async function loadHistory() {
      try {
        const response = await api.history({
          location: submittedLocation,
          date: historyDate,
          lang: "en",
        });
        if (active) {
          setHistory(response);
        }
      } catch (caughtError) {
        if (active) {
          setHistory(null);
          setError(
            caughtError instanceof Error ? caughtError.message : "History failed to load.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadHistory();

    return () => {
      active = false;
    };
  }, [historyDate, submittedLocation]);

  const events = useMemo(() => history?.globalEvents.slice(0, 5) ?? [], [history]);
  const facts = history?.location?.facts ?? [];

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedLocation = location.trim();
    if (trimmedLocation) {
      setSubmittedLocation(trimmedLocation);
    }
  }

  return (
    <section className="space-y-3" aria-label="Local knowledge and history">
      <Card className="p-3">
        <form className="space-y-3" onSubmit={submitLocation}>
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
              <MapPin aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            </span>
            <div className="min-w-0">
              <p className="text-lg font-black leading-tight text-slate-950">
                Facts
              </p>
              <p className="mt-1 text-sm font-bold text-slate-500">
                {history?.location?.title ?? submittedLocation}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-[1fr_auto] gap-2">
            <label className="block">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Location
              </span>
              <input
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>

            <label className="block w-36">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Date
              </span>
              <input
                value={historyDate}
                onChange={(event) => setHistoryDate(event.target.value)}
                type="date"
                className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>
          </div>

          <button
            type="submit"
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
          >
            <Search aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
            Update
          </button>
        </form>
      </Card>

      {loading ? (
        <Card>
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm font-black text-slate-500">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading facts
          </div>
        </Card>
      ) : error ? (
        <Card>
          <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
            {error}
          </p>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden p-0">
            {history?.location?.thumbnailUrl ? (
              <img
                src={history.location.thumbnailUrl}
                alt=""
                className="h-36 w-full object-cover"
              />
            ) : null}
            <div className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-black uppercase tracking-normal text-saints-red">
                    Local snapshot
                  </p>
                  <h2 className="mt-1 text-2xl font-black leading-tight text-slate-950">
                    {history?.location?.title ?? submittedLocation}
                  </h2>
                  {history?.location?.description ? (
                    <p className="mt-1 text-sm font-bold text-slate-500">
                      {history.location.description}
                    </p>
                  ) : null}
                </div>
                {history?.location?.articleUrl ? (
                  <a
                    href={history.location.articleUrl}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Open article for ${history.location.title}`}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-950 transition hover:bg-saints-red hover:text-white focus:outline-none focus:ring-4 focus:ring-saints-red/20"
                  >
                    <ExternalLink aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </a>
                ) : null}
              </div>

              {history?.partial && history.warnings.length > 0 ? (
                <p className="rounded-2xl bg-amber-50 px-3 py-2 text-sm font-bold text-amber-800">
                  Some sources are taking longer than usual, so this is a partial set.
                </p>
              ) : null}
            </div>
          </Card>

          {facts.length > 0 ? (
            <section className="grid gap-2" aria-label="Location facts">
              {facts.map((fact, index) => (
                <div
                  key={fact}
                  className="rounded-2xl border border-slate-200 bg-white p-3 shadow-soft"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-red-50 text-saints-red">
                      <Sparkles aria-hidden="true" className="h-4 w-4" strokeWidth={2.5} />
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-black uppercase tracking-normal text-saints-red">
                        Did you know #{index + 1}
                      </p>
                      <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
                        {fact}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </section>
          ) : null}

          <Card className="p-4">
            <div className="mb-3 flex items-center gap-2 text-saints-red">
              <CalendarDays aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              <p className="text-sm font-black uppercase tracking-normal">
                This day in history
              </p>
            </div>

            <div className="space-y-3">
              {events.map((event) => (
                <div key={`${event.year}-${event.text}`} className="flex gap-3">
                  <div className="flex w-16 shrink-0 justify-end">
                    <span className="h-fit rounded-full bg-saints-black px-2.5 py-1 text-xs font-black text-white">
                      {event.year}
                    </span>
                  </div>
                  <div className="min-w-0 border-l-2 border-red-100 pb-3 pl-3 last:pb-0">
                    <p className="text-sm font-semibold leading-relaxed text-slate-700">
                      {event.text}
                    </p>
                    {event.links[0]?.link ? (
                      <a
                        href={event.links[0].link}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-xs font-black uppercase tracking-normal text-saints-red"
                      >
                        <BookOpen aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
                        Read more
                      </a>
                    ) : null}
                  </div>
                </div>
              ))}
              {events.length === 0 ? (
                <p className="rounded-2xl bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-600">
                  No history events are available for this date just now.
                </p>
              ) : null}
            </div>
          </Card>
        </>
      )}
    </section>
  );
}
