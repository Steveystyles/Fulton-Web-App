import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  Lock,
  MapPinned,
  RotateCcw,
  Trophy,
  Type,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Card } from "../components/Card";
import {
  ApiError,
  api,
  type DailyMapGameLevel,
  type DailyMapGameResponse,
  type DailyMapGameResult,
  type DailyMapSnapSelection,
  type MapPoint,
} from "../lib/api";

const labelledTileUrl =
  (import.meta.env.VITE_FULTONS_MAP_TILE_URL as string | undefined) ||
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}";

const noLabelTileUrl =
  (import.meta.env.VITE_FULTONS_MAP_TILE_URL_NO_LABELS as string | undefined) ||
  "https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}@2x.png";

const tileAttribution =
  (import.meta.env.VITE_FULTONS_MAP_TILE_ATTRIBUTION as string | undefined) ||
  "Tiles &copy; Esri";

const noLabelTileAttribution =
  (import.meta.env.VITE_FULTONS_MAP_TILE_ATTRIBUTION_NO_LABELS as string | undefined) ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

function tileUrlForLabels(mapLabels: boolean) {
  return mapLabels ? labelledTileUrl : noLabelTileUrl;
}

function readableTileOptions(mapLabels: boolean): L.TileLayerOptions {
  const tileUrl = tileUrlForLabels(mapLabels);
  const usesRetinaTiles = tileUrl.includes("@2x");
  return {
    attribution: mapLabels ? tileAttribution : noLabelTileAttribution,
    maxZoom: 19,
    tileSize: usesRetinaTiles ? 512 : 256,
    zoomOffset: usesRetinaTiles ? -1 : 0,
  };
}

function defaultMapZoom() {
  return 1;
}

function shortDate(value?: string) {
  if (!value) {
    return "";
  }
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
  }).format(new Date(year, month - 1, day));
}

function markerIcon(kind: "guess" | "answer") {
  return L.divIcon({
    className: `daily-map-pin daily-map-pin--${kind}`,
    html: "<span></span>",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

type MapCanvasProps = {
  level: DailyMapGameLevel;
  mapLabels: boolean;
  acceptedSelection: DailyMapSnapSelection | undefined;
  draftSelection: DailyMapSnapSelection | null;
  selectionNotice: string;
  snapLoading: boolean;
  onMapPick: (point: MapPoint, zoom: number) => void;
  onAcceptDraft: () => void;
  onRejectDraft: () => void;
  onCycleDraft: (direction: -1 | 1) => void;
  onDismissSelectionNotice: () => void;
};

function MapCanvas({
  level,
  mapLabels,
  acceptedSelection,
  draftSelection,
  selectionNotice,
  snapLoading,
  onMapPick,
  onAcceptDraft,
  onRejectDraft,
  onCycleDraft,
  onDismissSelectionNotice,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);

  useEffect(() => {
    if (containerRef.current === null || mapRef.current !== null) {
      return;
    }

    const map = L.map(containerRef.current, {
      attributionControl: true,
      minZoom: 1,
      worldCopyJump: true,
      zoomControl: false,
    }).setView([25, 0], defaultMapZoom());

    L.control.zoom({ position: "bottomright" }).addTo(map);
    const layer = L.layerGroup().addTo(map);
    mapRef.current = map;
    layerRef.current = layer;

    const resizeTimer = window.setTimeout(() => {
      if (mapRef.current === map) {
        map.invalidateSize();
      }
    }, 50);

    return () => {
      window.clearTimeout(resizeTimer);
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      tileLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map === null) {
      return;
    }
    if (tileLayerRef.current !== null) {
      tileLayerRef.current.remove();
    }
    tileLayerRef.current = L.tileLayer(
      tileUrlForLabels(mapLabels),
      readableTileOptions(mapLabels),
    ).addTo(map);
  }, [mapLabels]);

  useEffect(() => {
    const map = mapRef.current;
    if (map === null) {
      return undefined;
    }
    const currentMap = map;

    function handleClick(event: L.LeafletMouseEvent) {
      if (level.submitted) {
        return;
      }
      onMapPick({
        lat: event.latlng.lat,
        lng: event.latlng.lng,
      }, currentMap.getZoom());
    }

    map.on("click", handleClick);
    return () => {
      map.off("click", handleClick);
    };
  }, [level.submitted, onMapPick]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (map === null || layer === null) {
      return;
    }

    layer.clearLayers();
    const resizeTimer = window.setTimeout(() => {
      if (mapRef.current === map) {
        map.invalidateSize();
      }
    }, 20);

    if (level.result !== undefined) {
      const guess: L.LatLngTuple = [
        level.result.guessedPoint.lat,
        level.result.guessedPoint.lng,
      ];
      const answer: L.LatLngTuple = [
        level.result.answerPoint.lat,
        level.result.answerPoint.lng,
      ];

      const targetCircle = L.circle(answer, {
        radius: level.result.targetRadiusMeters,
        color: "#059669",
        fillColor: "#10b981",
        fillOpacity: 0.1,
        interactive: false,
        weight: 2,
      }).addTo(layer);
      if (!level.result.insideTargetArea) {
        L.polyline([guess, answer], {
          color: "#d71920",
          dashArray: "6 6",
          opacity: 0.78,
          weight: 3,
        }).addTo(layer);
      }
      L.marker(guess, { icon: markerIcon("guess") }).addTo(layer);
      L.marker(answer, { icon: markerIcon("answer") }).addTo(layer);
      const bounds = L.latLngBounds([guess, answer]);
      bounds.extend(targetCircle.getBounds());
      map.fitBounds(bounds.pad(0.18), {
        animate: false,
        maxZoom: 12,
      });
      return () => window.clearTimeout(resizeTimer);
    }

    const activeSelection = draftSelection ?? acceptedSelection;
    if (activeSelection !== undefined && activeSelection !== null) {
      const point: L.LatLngTuple = [activeSelection.point.lat, activeSelection.point.lng];
      const marker = L.marker(point, {
        draggable: false,
        icon: markerIcon("guess"),
      }).addTo(layer);
      map.setView(point, Math.max(map.getZoom(), window.innerWidth < 420 ? 5 : 4), { animate: false });
      return () => window.clearTimeout(resizeTimer);
    }

    map.setView([25, 0], defaultMapZoom(), { animate: false });
    return () => window.clearTimeout(resizeTimer);
  }, [acceptedSelection, draftSelection, level]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
      <div
        ref={containerRef}
        className="h-[22rem] w-full min-[420px]:h-[26rem]"
        aria-label={`${level.title} guessing map`}
      />
      {snapLoading ? (
        <div className="absolute left-3 top-3 z-[700] inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-black text-slate-700 shadow-lg">
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin text-saints-red" />
          Finding place
        </div>
      ) : null}
      {selectionNotice && draftSelection === null && !snapLoading && !level.submitted ? (
        <div
          className="absolute left-3 right-3 top-3 z-[700] flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-2 text-amber-950 shadow-xl"
          aria-live="polite"
        >
          <CircleAlert aria-hidden="true" className="h-5 w-5 shrink-0 text-amber-600" strokeWidth={2.6} />
          <p className="min-w-0 flex-1 text-sm font-black leading-snug">{selectionNotice}</p>
          <button
            type="button"
            aria-label="Dismiss place selection message"
            onClick={onDismissSelectionNotice}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-amber-200 bg-white/80 text-amber-800 saints-focus"
          >
            <X aria-hidden="true" className="h-5 w-5" strokeWidth={3} />
          </button>
        </div>
      ) : null}
      {draftSelection !== null && !level.submitted ? (
        <div
          className="absolute left-3 right-3 top-3 z-[700] rounded-xl border border-slate-200 bg-white p-3 shadow-xl"
          aria-live="polite"
        >
          <div className="min-w-0">
            <p className="text-[0.62rem] font-black uppercase tracking-normal text-saints-red">
              {draftSelection.snapped ? "Selected place" : "Selected point"}
            </p>
            <p className="mt-0.5 break-words text-xl font-black leading-tight text-slate-950">
              {draftSelection.name}
            </p>
            {draftSelection.admin1 || draftSelection.countryCode ? (
              <p className="mt-1 break-words text-sm font-bold leading-snug text-slate-500">
                {[draftSelection.admin1, draftSelection.countryCode].filter(Boolean).join(", ")}
              </p>
            ) : null}
            {(draftSelection.alternatives?.length ?? 0) > 1 ? (
              <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
                {(draftSelection.selectedIndex ?? 0) + 1}/{draftSelection.alternatives?.length}
              </p>
            ) : null}
          </div>
          <div className="mt-3 flex items-center gap-2">
            {(draftSelection.alternatives?.length ?? 0) > 1 ? (
              <>
                <button
                  type="button"
                  aria-label="Previous nearby place"
                  onClick={() => onCycleDraft(-1)}
                  className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 saints-focus"
                >
                  <ChevronLeft aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
                </button>
                <button
                  type="button"
                  aria-label="Next nearby place"
                  onClick={() => onCycleDraft(1)}
                  className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 saints-focus"
                >
                  <ChevronRight aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
                </button>
              </>
            ) : null}
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                aria-label="Reject selected place"
                onClick={onRejectDraft}
                className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 saints-focus"
              >
                <X aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
              </button>
              <button
                type="button"
                aria-label="Accept selected place"
                onClick={onAcceptDraft}
                className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-emerald-600 text-white shadow-sm saints-focus"
              >
                <Check aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function MapGame() {
  const [game, setGame] = useState<DailyMapGameResponse | null>(null);
  const [selectedLevelId, setSelectedLevelId] = useState<number | null>(null);
  const [pendingSelections, setPendingSelections] = useState<Record<number, DailyMapSnapSelection>>({});
  const [draftSelection, setDraftSelection] = useState<DailyMapSnapSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectionNotice, setSelectionNotice] = useState("");
  const [snapLoading, setSnapLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [revealedHintCount, setRevealedHintCount] = useState(0);
  const lockButtonRef = useRef<HTMLButtonElement | null>(null);
  const [mapLabels, setMapLabels] = useState(() => {
    try {
      return window.localStorage.getItem("fultons:daily-map:labels") !== "off";
    } catch {
      return true;
    }
  });

  const loadGame = useCallback(async () => {
    try {
      const response = await api.dailyMapGame();
      setGame(response);
      setError("");
      setSelectedLevelId((current) => {
        if (current !== null && response.levels.some((level) => level.id === current)) {
          return current;
        }
        return response.levels.find((level) => !level.submitted)?.id ?? response.levels[0]?.id ?? null;
      });
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Map game failed to load.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGame();
  }, [loadGame]);

  useEffect(() => {
    setDraftSelection(null);
    setSelectionNotice("");
    setSnapLoading(false);
    setRevealedHintCount(0);
  }, [selectedLevelId]);

  useEffect(() => {
    try {
      window.localStorage.setItem("fultons:daily-map:labels", mapLabels ? "on" : "off");
    } catch {
      // The toggle still works for the current session if storage is unavailable.
    }
  }, [mapLabels]);

  const levels = game?.levels ?? [];
  const selectedLevel = useMemo(
    () => levels.find((level) => level.id === selectedLevelId) ?? levels[0],
    [levels, selectedLevelId],
  );
  const pendingSelection = selectedLevel ? pendingSelections[selectedLevel.id] : undefined;
  const pendingPoint = pendingSelection?.point;
  const totalScore = levels.reduce((total, level) => total + (level.result?.score ?? 0), 0);
  const completed = levels.filter((level) => level.submitted).length;
  const currentRevealedHintCount = selectedLevel?.result?.revealedHintCount ?? revealedHintCount;
  const clues = selectedLevel?.clues ?? [];
  const visibleClues = clues.slice(0, Math.min(clues.length, currentRevealedHintCount + 1));
  const nextClue = selectedLevel?.submitted ? undefined : clues[currentRevealedHintCount + 1];
  const currentMaxPoints =
    selectedLevel?.result?.maxPoints ?? clues[currentRevealedHintCount]?.maxPoints ?? selectedLevel?.maxPoints ?? 0;

  const pickPointForSelected = useCallback(
    async (point: MapPoint, zoom: number) => {
      if (selectedLevel === undefined || selectedLevel.submitted || snapLoading) {
        return;
      }
      const levelId = selectedLevel.id;
      setSnapLoading(true);
      setError("");
      setSelectionNotice("");
      setDraftSelection(null);
      try {
        const selection = await api.snapDailyMapGuess(levelId, point, zoom);
        if (!selection.snapped) {
          setSelectionNotice(
            "No nearby place found. Try tapping closer to a town, city, or landmark.",
          );
          return;
        }
        setDraftSelection(selection);
      } catch (caughtError) {
        if (caughtError instanceof ApiError) {
          if (caughtError.status === 400 && caughtError.message.includes("today")) {
            setSelectionNotice("Map refreshed for today's game. Try another tap.");
            await loadGame();
            return;
          }
          if (caughtError.status === 422) {
            setSelectionNotice(caughtError.message);
            return;
          }
        }
        setError(caughtError instanceof Error ? caughtError.message : "Place selection failed.");
      } finally {
        setSnapLoading(false);
      }
    },
    [loadGame, selectedLevel, snapLoading],
  );

  const cycleDraftSelection = useCallback((direction: -1 | 1) => {
    setDraftSelection((current) => {
      const alternatives = current?.alternatives;
      if (current === null || alternatives === undefined || alternatives.length < 2) {
        return current;
      }
      const currentIndex = current.selectedIndex ?? 0;
      const nextIndex = (currentIndex + direction + alternatives.length) % alternatives.length;
      return {
        ...alternatives[nextIndex],
        alternatives,
        selectedIndex: nextIndex,
      };
    });
  }, []);

  const acceptDraftSelection = useCallback(() => {
    if (selectedLevel === undefined || draftSelection === null) {
      return;
    }
    setPendingSelections((current) => ({ ...current, [selectedLevel.id]: draftSelection }));
    setDraftSelection(null);
    setSelectionNotice("");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        lockButtonRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
        lockButtonRef.current?.focus({ preventScroll: true });
      });
    });
  }, [draftSelection, selectedLevel]);

  const rejectDraftSelection = useCallback(() => {
    setDraftSelection(null);
    setSelectionNotice("");
  }, []);

  const dismissSelectionNotice = useCallback(() => {
    setSelectionNotice("");
  }, []);

  async function submitGuess() {
    if (
      selectedLevel === undefined ||
      pendingPoint === undefined ||
      draftSelection !== null ||
      selectedLevel.submitted
    ) {
      return;
    }
    setSubmitting(true);
    setError("");
    setSelectionNotice("");
    try {
      const response = await api.submitDailyMapGuess(selectedLevel.id, pendingPoint, {
        selectedName: pendingSelection?.name,
        revealedHintCount,
      });
      setGame((current) => {
        if (current === null) {
          return current;
        }
        return {
          ...current,
          completedLevels: current.levels.filter((level) =>
            level.id === selectedLevel.id ? true : level.submitted,
          ).length,
          levels: current.levels.map((level) =>
            level.id === selectedLevel.id
              ? { ...level, submitted: true, result: response.result }
              : level,
          ),
        };
      });
      setPendingSelections((current) => {
        const next = { ...current };
        delete next[selectedLevel.id];
        return next;
      });
      setDraftSelection(null);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Guess failed to submit.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <section className="page-fade space-y-3" aria-label="Daily map game">
        <Card>
          <div className="flex min-h-32 items-center justify-center gap-2 text-sm font-black text-slate-500">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading map game
          </div>
        </Card>
      </section>
    );
  }

  if (selectedLevel === undefined || game === null) {
    return (
      <section className="page-fade space-y-3" aria-label="Daily map game">
        <Card className="space-y-3">
          <p className="text-sm font-bold text-slate-600">
            Today&apos;s map game is not available yet.
          </p>
          {error ? (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
              {error}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => void loadGame()}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-saints-black px-4 text-sm font-black text-white saints-focus"
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            Try again
          </button>
        </Card>
      </section>
    );
  }

  return (
    <section className="page-fade space-y-3 pb-2" aria-label="Daily map game">
      <Card className="overflow-hidden p-0">
        <div className="bg-saints-black px-4 py-3 text-white">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-[0.68rem] font-black uppercase tracking-normal text-white/65">
                <MapPinned aria-hidden="true" className="h-3.5 w-3.5 text-saints-red" />
                Daily map
              </p>
              <h1 className="mt-1 text-2xl font-black leading-tight">Pin the place</h1>
            </div>
            <div className="shrink-0 rounded-lg bg-white/10 px-3 py-2 text-right">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
                {shortDate(game.date)}
              </p>
              <p className="mt-0.5 text-xl font-black leading-none">
                {totalScore}
                <span className="text-sm text-white/55">/{game.maxScore}</span>
              </p>
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
            <div
              className="h-full rounded-full bg-saints-red"
              style={{ width: `${Math.round((completed / Math.max(1, levels.length)) * 100)}%` }}
            />
          </div>
        </div>

        <div className="space-y-3 p-3">
          <div className="grid">
            <button
              type="button"
              aria-pressed={mapLabels}
              aria-label={mapLabels ? "Turn map text off" : "Turn map text on"}
              onClick={() => setMapLabels((current) => !current)}
              className={[
                "flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-base font-black leading-tight transition saints-focus",
                mapLabels
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-slate-200 bg-white text-slate-500",
              ].join(" ")}
            >
              <Type aria-hidden="true" className="h-4 w-4" strokeWidth={2.6} />
              <span>{mapLabels ? "Map text on" : "Map text off"}</span>
            </button>
          </div>

          <div className="space-y-2" aria-label="Map game clues">
            {visibleClues.map((clue) => (
              <div
                key={clue.id}
                className={[
                  "rounded-xl border px-3 py-3",
                  clue.revealsName
                    ? "border-saints-red/25 bg-red-50"
                    : "border-slate-200 bg-slate-50",
                ].join(" ")}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                    {clue.title}
                  </p>
                  <p className="shrink-0 text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
                    Max {clue.maxPoints} pts
                  </p>
                </div>
                <p className="mt-1 text-base font-black leading-snug text-slate-950">
                  {clue.text}
                </p>
              </div>
            ))}
            {nextClue ? (
              <button
                type="button"
                onClick={() => setRevealedHintCount((current) => Math.min(3, current + 1))}
                className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-black text-slate-700 transition hover:border-saints-red/40 saints-focus"
              >
                Reveal {nextClue.title.toLowerCase()} - max {nextClue.maxPoints} pts
              </button>
            ) : null}
          </div>

          <MapCanvas
            key={selectedLevel.id}
            level={selectedLevel}
            mapLabels={mapLabels}
            acceptedSelection={pendingSelection}
            draftSelection={draftSelection}
            selectionNotice={selectionNotice}
            snapLoading={snapLoading}
            onMapPick={pickPointForSelected}
            onAcceptDraft={acceptDraftSelection}
            onRejectDraft={rejectDraftSelection}
            onCycleDraft={cycleDraftSelection}
            onDismissSelectionNotice={dismissSelectionNotice}
          />

          {selectedLevel.result ? (
            <ResultPanel result={selectedLevel.result} />
          ) : (
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
              <div className="min-w-0 rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
                  Current pin
                </p>
                <p className="mt-0.5 truncate text-sm font-bold text-slate-700">
                  {pendingSelection
                    ? pendingSelection.name
                    : draftSelection
                      ? "Awaiting tick"
                      : selectionNotice
                        ? "Try another tap"
                      : snapLoading
                        ? "Finding place"
                        : "No pin accepted"}
                </p>
              </div>
              <button
                ref={lockButtonRef}
                type="button"
                onClick={() => void submitGuess()}
                disabled={pendingPoint === undefined || draftSelection !== null || snapLoading || submitting}
                className={[
                  "inline-flex min-h-12 min-w-[8.5rem] items-center justify-center gap-2 rounded-lg px-4 text-sm font-black transition saints-focus",
                  pendingPoint === undefined || draftSelection !== null || snapLoading || submitting
                    ? "bg-slate-200 text-slate-400"
                    : "bg-saints-red text-white shadow-sm hover:bg-saints-redDark",
                ].join(" ")}
              >
                {submitting ? (
                  <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <Lock aria-hidden="true" className="h-4 w-4" />
                )}
                Lock {currentMaxPoints}
              </button>
            </div>
          )}

          {error ? (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
              {error}
            </p>
          ) : null}
        </div>
      </Card>
    </section>
  );
}

function ResultPanel({ result }: { result: DailyMapGameResult }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
      <div className="grid grid-cols-3 gap-2 text-center">
        <ResultMetric label="Score" value={`${result.score}`} icon={<Trophy className="h-4 w-4" />} />
        <ResultMetric label="Result" value={result.correct ? "Correct" : "Wrong"} />
        <ResultMetric label="Help used" value={`${result.revealedHintCount + 1}`} />
      </div>
      <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2">
        <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
          {result.place.name}
        </p>
        {result.selectedPlace.name && result.selectedPlace.name !== result.place.name ? (
          <p className="mt-1 text-sm font-black text-slate-700">
            You selected {result.selectedPlace.name}
          </p>
        ) : null}
        <p className="mt-1 text-sm font-black text-slate-700">{result.band}</p>
        <p className="mt-1 text-sm font-semibold leading-snug text-slate-600">
          {result.place.revealText}
        </p>
      </div>
    </div>
  );
}

function ResultMetric({
  icon,
  label,
  value,
}: {
  icon?: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex min-h-[4.4rem] min-w-0 flex-col items-center justify-center rounded-lg bg-slate-50 px-2 py-2">
      <div className="flex items-center justify-center gap-1 text-saints-red">
        {icon}
        <p className="break-words text-lg font-black leading-tight text-slate-950">{value}</p>
      </div>
      <p className="mt-1 text-[0.62rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
    </div>
  );
}
