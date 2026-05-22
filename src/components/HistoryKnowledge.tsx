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
  type HistoryLocationImage,
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

function formatHistoryDate(dateValue: string) {
  const [year, month, day] = dateValue.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(year, month - 1, day));
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

function locationImages(location: HistoryResponse["location"]): HistoryLocationImage[] {
  if (location?.images?.length) {
    return location.images;
  }
  if (location?.thumbnailUrl) {
    return [{
      url: location.thumbnailUrl,
      title: location.title,
      sourceName: "Wikipedia",
      sourceUrl: location.articleUrl,
    }];
  }
  return [];
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
  const [filtersOpen, setFiltersOpen] = useState(false);
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
  const townImages = useMemo(() => locationImages(history?.location ?? null), [history]);

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedLocation = location.trim();
    if (trimmedLocation) {
      setSubmittedLocation({ location: trimmedLocation, source: "manual" });
      setLocationNotice("Showing facts for your searched location.");
      setFiltersOpen(false);
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
        setFiltersOpen(false);
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

          <div className="grid grid-cols-2 gap-2 rounded-2xl bg-slate-50 p-3">
            <ControlValue
              label="Location"
              value={history?.location?.title ?? submittedLocation.location}
            />
            <ControlValue label="Date" value={formatHistoryDate(historyDate)} />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <DateChangeButton historyDate={historyDate} onChange={setHistoryDate} />
            <button
              type="button"
              onClick={() => setFiltersOpen((current) => !current)}
              aria-expanded={filtersOpen}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm font-black text-slate-950 transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
            >
              <MapPin aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              Change location
            </button>
          </div>

          {filtersOpen ? (
            <div className="space-y-3 rounded-2xl bg-slate-50 p-3">
              <p className="text-xs font-bold leading-relaxed text-slate-600">
                {locationNotice}
              </p>
              <label className="block min-w-0">
                <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                  Place
                </span>
                <input
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  placeholder="Town or city"
                  className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
                />
              </label>
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
            </div>
          ) : null}
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
          <LocalStoryCard history={history} submittedLocation={submittedLocation} />

          {facts.length > 0 ? (
            <section className="space-y-2" aria-label="Location facts">
              <p className="px-1 text-sm font-black uppercase tracking-normal text-saints-red">
                Interesting facts
              </p>
              <div className="grid gap-2">
                {facts.map((fact, index) => {
                  const meta = themeMeta[fact.theme] ?? themeMeta.general;
                  const Icon = meta.icon;
                  const factImage = townImages[index % Math.max(townImages.length, 1)];
                  return (
                    <div
                      key={`${index}-${fact.title}`}
                      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-soft"
                    >
                      {factImage ? (
                        <div className="relative h-24 overflow-hidden">
                          <img
                            key={factImage.url}
                            src={factImage.url}
                            alt=""
                            loading="lazy"
                            onError={(event) => {
                              event.currentTarget.hidden = true;
                            }}
                            className="h-full w-full object-cover"
                          />
                          <div className="absolute inset-0 bg-gradient-to-r from-slate-950/35 via-slate-950/5 to-transparent" />
                        </div>
                      ) : null}
                      <div className="flex items-start gap-3 p-3">
                        <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${meta.className}`}>
                          <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={2.5} />
                        </span>
                        <div className="min-w-0 flex-1">
                          <span className={`inline-flex rounded-full px-2.5 py-1 text-[0.7rem] font-black uppercase tracking-normal ${meta.className}`}>
                            {meta.label}
                          </span>
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

function ControlValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 truncate text-sm font-black text-slate-950">{value}</p>
    </div>
  );
}

function DateChangeButton({
  historyDate,
  onChange,
}: {
  historyDate: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="relative inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-2 overflow-hidden rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm font-black text-slate-950 transition hover:bg-slate-50 focus-within:ring-4 focus-within:ring-saints-red/20">
      <CalendarDays aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
      <span>
        Change date
      </span>
      <input
        value={historyDate}
        onChange={(event) => onChange(event.target.value)}
        type="date"
        aria-label="Change facts date"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </label>
  );
}

function LocalStoryCard({
  history,
  submittedLocation,
}: {
  history: HistoryResponse | null;
  submittedLocation: HistoryLocationQuery;
}) {
  const title = history?.location?.title ?? submittedLocation.location;
  const images = locationImages(history?.location ?? null);

  return (
    <Card className="overflow-hidden p-0">
      <TownStoryBackdrop
        articleUrl={history?.location?.articleUrl ?? null}
        description={history?.location?.description ?? null}
        images={images}
        title={title}
      />
      <div className="space-y-3 p-4">

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
  );
}

function TownStoryBackdrop({
  articleUrl,
  description,
  images,
  title,
}: {
  articleUrl: string | null;
  description: string | null;
  images: HistoryLocationImage[];
  title: string;
}) {
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const slideKey = images.map((image) => image.url).join("|");

  useEffect(() => {
    setActiveImageIndex(0);
  }, [slideKey]);

  useEffect(() => {
    if (images.length < 2) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      setActiveImageIndex((current) => (current + 1) % images.length);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [images.length, slideKey]);

  return (
    <div className="relative min-h-44 overflow-hidden bg-slate-950">
      {images.map((image, index) => (
        <img
          key={image.url}
          src={image.url}
          alt=""
          aria-hidden="true"
          loading={index === 0 ? "eager" : "lazy"}
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
          className={`absolute inset-0 h-full w-full object-cover transition duration-1000 ${
            index === activeImageIndex ? "scale-100 opacity-100" : "scale-105 opacity-0"
          }`}
        />
      ))}
      <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/60 to-slate-950/15" />
      <div className="relative flex min-h-44 flex-col justify-end gap-2 p-4 text-white">
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-normal text-white/80">
              Local story
            </p>
            <h2 className="mt-1 text-2xl font-black leading-tight">{title}</h2>
          </div>
          {articleUrl ? (
            <a
              href={articleUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open article for ${title}`}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/90 text-slate-950 transition hover:bg-saints-red hover:text-white focus:outline-none focus:ring-4 focus:ring-white/30"
            >
              <ExternalLink aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            </a>
          ) : null}
        </div>
        {description ? (
          <p className="max-w-xl text-sm font-bold leading-snug text-white/85">
            {description}
          </p>
        ) : null}
        {images.length > 1 ? (
          <div className="flex gap-1.5" aria-hidden="true">
            {images.map((image, index) => (
              <span
                key={`${image.url}-dot`}
                className={`h-1.5 rounded-full transition-all ${
                  index === activeImageIndex ? "w-6 bg-saints-red" : "w-1.5 bg-white/55"
                }`}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
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
