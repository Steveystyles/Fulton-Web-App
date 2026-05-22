import {
  BadgeCheck,
  BookOpen,
  Cake,
  CalendarDays,
  ExternalLink,
  Factory,
  Landmark,
  LoaderCircle,
  MapPin,
  Navigation,
  Search,
  Sparkles,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  api,
  type HistoryEvent,
  type HistoryFact,
  type HistoryLocationProfile,
  type HistoryResponse,
} from "../lib/api";
import { Card } from "./Card";

const defaultLocation = "Paisley";

const themeMeta: Record<HistoryFact["theme"], { label: string; icon: LucideIcon; className: string }> = {
  history: {
    label: "History",
    icon: BookOpen,
    className: "bg-red-50 text-saints-red",
  },
  landmark: {
    label: "Landmark",
    icon: Landmark,
    className: "bg-amber-50 text-amber-700",
  },
  industry: {
    label: "Industry",
    icon: Factory,
    className: "bg-slate-100 text-slate-800",
  },
  culture: {
    label: "Culture",
    icon: Sparkles,
    className: "bg-purple-50 text-purple-700",
  },
  people: {
    label: "People",
    icon: Users,
    className: "bg-blue-50 text-blue-700",
  },
  date: {
    label: "Anniversary",
    icon: CalendarDays,
    className: "bg-emerald-50 text-emerald-700",
  },
  general: {
    label: "Local fact",
    icon: BadgeCheck,
    className: "bg-slate-100 text-slate-800",
  },
};

type HistoryLocationQuery = {
  location: string;
  source: "manual" | "device" | "fallback";
};

function todayIsoDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isFactObject(fact: string | HistoryFact): fact is HistoryFact {
  return typeof fact !== "string";
}

function normaliseFact(fact: string | HistoryFact, index: number): HistoryFact {
  if (isFactObject(fact)) {
    return fact;
  }

  return {
    title: `Local fact #${index + 1}`,
    text: fact,
    theme: "general",
    sourceName: "Wikipedia",
    sourceUrl: null,
    confidence: "medium",
  };
}

function formatProfileSummary(profile: HistoryLocationProfile) {
  const placeKind = profile.types.slice(0, 2).join(" and ");
  const area = profile.areas[0];
  const areaText = area ? ` in ${area}` : "";
  const countryText = profile.country ? `, ${profile.country}` : "";

  if (placeKind) {
    return `${profile.title} is listed as ${placeKind}${areaText}${countryText}.`;
  }
  if (area || profile.country) {
    return `${profile.title} is listed${areaText}${countryText}.`;
  }
  return `${profile.title} at a glance.`;
}

async function reverseGeocode(latitude: number, longitude: number) {
  const params = new URLSearchParams({
    format: "jsonv2",
    lat: String(latitude),
    lon: String(longitude),
    zoom: "14",
    addressdetails: "1",
  });
  const response = await fetch(`https://nominatim.openstreetmap.org/reverse?${params}`);
  if (!response.ok) {
    throw new Error("Location lookup failed.");
  }

  const payload = await response.json();
  const address = payload?.address ?? {};
  const place =
    address.town ??
    address.city ??
    address.village ??
    address.locality ??
    address.borough ??
    address.city_district ??
    address.hamlet ??
    address.municipality;

  if (place) {
    return String(place);
  }
  if (typeof payload?.display_name === "string" && address.county) {
    const parts = payload.display_name
      .split(",")
      .map((part: string) => part.trim())
      .filter(Boolean);
    const countyIndex = parts.findIndex((part: string) => part === address.county);
    if (countyIndex > 0) {
      return parts[countyIndex - 1];
    }
  }
  if (address.county) {
    return String(address.county);
  }
  if (typeof payload?.display_name === "string") {
    return payload.display_name.split(",").slice(0, 2).join(",").trim();
  }

  throw new Error("Could not identify your nearest town.");
}

function getDeviceLocation(): Promise<HistoryLocationQuery> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Device location is not available."));
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const nextLocation = await reverseGeocode(
            position.coords.latitude,
            position.coords.longitude,
          );
          resolve({ location: nextLocation, source: "device" });
        } catch (error) {
          reject(error);
        }
      },
      () => reject(new Error("Location permission was not granted.")),
      { enableHighAccuracy: false, maximumAge: 60 * 60 * 1000, timeout: 7000 },
    );
  });
}

export function HistoryKnowledge() {
  const [location, setLocation] = useState(defaultLocation);
  const [submittedLocation, setSubmittedLocation] = useState<HistoryLocationQuery>({
    location: defaultLocation,
    source: "fallback",
  });
  const [historyDate, setHistoryDate] = useState(todayIsoDate);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState("");
  const [locationNotice, setLocationNotice] = useState(
    "Use your device location for local facts, or search another place.",
  );

  useEffect(() => {
    let active = true;
    setLocating(true);

    void getDeviceLocation()
      .then((query) => {
        if (!active) {
          return;
        }
        setLocation(query.location);
        setSubmittedLocation(query);
        setLocationNotice("Showing facts near your device location. You can search another place anytime.");
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setLocationNotice("Location permission is optional. Showing Paisley until you search another place.");
      })
      .finally(() => {
        if (active) {
          setLocating(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    async function loadHistory() {
      try {
        const response = await api.history({
          location: submittedLocation.location,
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

  const eventGroups = useMemo(() => {
    const events = history?.globalEvents ?? [];
    return {
      history: events.filter((event) => (event.category ?? "history") === "history"),
      sport: events.filter((event) => event.category === "sport"),
      born: events.filter((event) => event.category === "born"),
    };
  }, [history]);
  const facts = useMemo(
    () => (history?.location?.facts ?? []).map((fact, index) => normaliseFact(fact, index)),
    [history],
  );

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedLocation = location.trim();
    if (trimmedLocation) {
      setSubmittedLocation({ location: trimmedLocation, source: "manual" });
      setLocationNotice("Showing facts for your searched location.");
    }
  }

  function useCurrentLocation() {
    setLocating(true);
    setError("");
    void getDeviceLocation()
      .then((query) => {
        setLocation(query.location);
        setSubmittedLocation(query);
        setLocationNotice("Showing facts near your device location. You can search another place anytime.");
      })
      .catch((caughtError) => {
        setLocationNotice(
          caughtError instanceof Error
            ? caughtError.message
            : "Device location could not be used just now.",
        );
      })
      .finally(() => setLocating(false));
  }

  return (
    <section className="space-y-3" aria-label="Local knowledge and history">
      <Card className="p-4">
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
                {history?.location?.title ?? submittedLocation.location}
              </p>
            </div>
          </div>

          <p className="rounded-2xl bg-slate-50 px-3 py-2 text-xs font-bold leading-relaxed text-slate-600">
            {locationNotice}
          </p>

          <div className="grid grid-cols-1 gap-2 min-[390px]:grid-cols-[minmax(0,1fr)_minmax(9.75rem,10.25rem)]">
            <label className="block min-w-0">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Location
              </span>
              <input
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="Town or city"
                className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>

            <label className="block min-w-0">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Date
              </span>
              <input
                value={historyDate}
                onChange={(event) => setHistoryDate(event.target.value)}
                type="date"
                className="mt-1 block h-12 w-full min-w-0 max-w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="submit"
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
            >
              <Search aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              Search
            </button>
            <button
              type="button"
              onClick={useCurrentLocation}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl border border-slate-300 bg-white px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
            >
              {locating ? (
                <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
              ) : (
                <Navigation aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              )}
              Near me
            </button>
          </div>

          <p className="text-xs font-semibold leading-relaxed text-slate-500">
            Location is sent only to fetch public facts for this page and is not saved to your account.
          </p>
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
                    Local story
                  </p>
                  <h2 className="mt-1 text-2xl font-black leading-tight text-slate-950">
                    {history?.location?.title ?? submittedLocation.location}
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

              {history?.location?.profile ? (
                <section className="rounded-2xl bg-slate-50 p-3" aria-label="Location summary">
                  <p className="text-xs font-black uppercase tracking-normal text-saints-red">
                    At a glance
                  </p>
                  <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
                    {formatProfileSummary(history.location.profile)}
                  </p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {history.location.profile.population ? (
                      <ProfileStat label="Population" value={history.location.profile.population} />
                    ) : null}
                    {history.location.profile.areas[0] ? (
                      <ProfileStat label="Area" value={history.location.profile.areas[0]} />
                    ) : null}
                    {history.location.profile.country ? (
                      <ProfileStat label="Country" value={history.location.profile.country} />
                    ) : null}
                    {history.location.profile.inception ? (
                      <ProfileStat label="Recorded" value={history.location.profile.inception} />
                    ) : null}
                  </div>
                  {history.location.profile.sourceUrl ? (
                    <a
                      href={history.location.profile.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-flex items-center gap-1 text-xs font-black uppercase tracking-normal text-saints-red"
                    >
                      <BookOpen aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
                      {history.location.profile.sourceName}
                    </a>
                  ) : null}
                </section>
              ) : null}
            </div>
          </Card>

          {facts.length > 0 ? (
            <section className="space-y-2" aria-label="Location facts">
              <p className="px-1 text-sm font-black uppercase tracking-normal text-saints-red">
                Interesting facts
              </p>
              <div className="grid gap-2">
                {facts.map((fact, index) => {
                  const meta = themeMeta[fact.theme] ?? themeMeta.general;
                  const Icon = meta.icon;
                  return (
                    <div
                      key={`${index}-${fact.title}`}
                      className="rounded-2xl border border-slate-200 bg-white p-3 shadow-soft"
                    >
                      <div className="flex items-start gap-3">
                        <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${meta.className}`}>
                          <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={2.5} />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`rounded-full px-2.5 py-1 text-[0.7rem] font-black uppercase tracking-normal ${meta.className}`}>
                              {meta.label}
                            </span>
                            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[0.7rem] font-black uppercase tracking-normal text-slate-500">
                              {fact.confidence} confidence
                            </span>
                          </div>
                          <p className="mt-2 text-sm font-black leading-snug text-slate-950">
                            {fact.title}
                          </p>
                          <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
                            {fact.text}
                          </p>
                          {fact.sourceUrl ? (
                            <a
                              href={fact.sourceUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-2 inline-flex items-center gap-1 text-xs font-black uppercase tracking-normal text-saints-red"
                            >
                              <BookOpen aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
                              {fact.sourceName}
                            </a>
                          ) : (
                            <p className="mt-2 text-xs font-black uppercase tracking-normal text-slate-400">
                              Source: {fact.sourceName}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : (
            <Card>
              <p className="rounded-2xl bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-600">
                No local facts are available for this place just now. Try a nearby town or city.
              </p>
            </Card>
          )}

          <Card className="p-4">
            <div className="mb-4 flex items-center gap-2 text-saints-red">
              <CalendarDays aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              <p className="text-sm font-black uppercase tracking-normal">
                This day in history
              </p>
            </div>

            <div className="space-y-4">
              <HistoryEventList title="Highlights" events={eventGroups.history} icon="history" />
              <HistoryEventList title="Sport" events={eventGroups.sport} icon="sport" />
              <HistoryEventList title="Born today" events={eventGroups.born} icon="born" />
              {(history?.globalEvents.length ?? 0) === 0 ? (
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

function ProfileStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-white p-2.5 shadow-sm">
      <p className="text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
      <p className="mt-1 break-words text-sm font-black leading-tight text-slate-950">
        {value}
      </p>
    </div>
  );
}

function HistoryEventList({
  events,
  icon,
  title,
}: {
  events: HistoryEvent[];
  icon: "history" | "sport" | "born";
  title: string;
}) {
  if (events.length === 0) {
    return null;
  }

  const Icon = icon === "sport" ? Trophy : icon === "born" ? Cake : BookOpen;

  return (
    <section aria-label={title}>
      <div className="mb-2 flex items-center gap-2 text-saints-black">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-saints-redSoft text-saints-red">
          <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
        </span>
        <p className="text-xs font-black uppercase tracking-normal">{title}</p>
      </div>

      <div className="space-y-3">
        {events.map((event) => (
          <div key={`${event.category ?? "history"}-${event.year}-${event.text}`} className="flex gap-3">
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
      </div>
    </section>
  );
}
