import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  Lock,
  Layers,
  MapPinned,
  PlayCircle,
  RotateCcw,
  Ruler,
  Trophy,
  Type,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Card } from "../components/Card";
import { useAuth } from "../context/AuthContext";
import { MapGamePromo } from "./MapGamePromo";
import {
  ApiError,
  api,
  type DailyMapAnchor,
  type DailyMapGameLevel,
  type DailyMapGameResponse,
  type DailyMapGameResult,
  type DailyMapSnapSelection,
  type MapPoint,
} from "../lib/api";

type MapStyle = "clear" | "detail";

const detailTileUrl =
  (import.meta.env.VITE_FULTONS_MAP_TILE_URL as string | undefined) ||
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}";

const clearBaseTileUrl =
  (import.meta.env.VITE_FULTONS_MAP_TILE_URL_CLEAR_BASE as string | undefined) ||
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

function tileUrls(mapStyle: MapStyle, mapLabels: boolean) {
  if (!mapLabels) {
    return [noLabelTileUrl];
  }
  return mapStyle === "clear" ? [clearBaseTileUrl] : [detailTileUrl];
}

function readableTileOptions(tileUrl: string, mapLabels: boolean): L.TileLayerOptions {
  const usesRetinaTiles = tileUrl.includes("@2x");
  const usesNativeStreetDetail = tileUrl.includes("World_Street_Map");
  const usesEnlargedLabels = mapLabels && !usesRetinaTiles && !usesNativeStreetDetail;
  const usesEsriTopographicTiles = tileUrl.includes("World_Topo_Map");
  return {
    attribution: mapLabels ? tileAttribution : noLabelTileAttribution,
    maxZoom: 19,
    maxNativeZoom: usesEsriTopographicTiles
      ? 14
      : usesEnlargedLabels
        ? 18
        : 19,
    tileSize: usesRetinaTiles || usesEnlargedLabels ? 512 : 256,
    zoomOffset: usesRetinaTiles || usesEnlargedLabels ? -1 : 0,
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

function escapedMapLabel(value: string) {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function mapAnchorIcon(name: string) {
  return L.divIcon({
    className: "daily-map-search-anchor",
    html: `<span>${escapedMapLabel(name)}</span>`,
    iconSize: [180, 42],
    iconAnchor: [90, 21],
  });
}

function formatMeasuredDistance(distanceMetres: number) {
  const distanceKilometres = distanceMetres / 1000;
  return `${new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: distanceKilometres < 100 ? 1 : 0,
  }).format(distanceKilometres)} km`;
}

type MapCanvasProps = {
  level: DailyMapGameLevel;
  mapLabels: boolean;
  mapStyle: MapStyle;
  mapAnchors: DailyMapAnchor[];
  acceptedSelection: DailyMapSnapSelection | undefined;
  draftSelection: DailyMapSnapSelection | null;
  selectionNotice: string;
  snapLoading: boolean;
  submitting: boolean;
  onMapPick: (point: MapPoint, zoom: number) => void;
  onUseDraft: () => void;
  onRejectDraft: () => void;
  onCycleDraft: (direction: -1 | 1) => void;
  onDismissSelectionNotice: () => void;
};

function MapCanvas({
  level,
  mapLabels,
  mapStyle,
  mapAnchors,
  acceptedSelection,
  draftSelection,
  selectionNotice,
  snapLoading,
  submitting,
  onMapPick,
  onUseDraft,
  onRejectDraft,
  onCycleDraft,
  onDismissSelectionNotice,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const measurementLayerRef = useRef<L.LayerGroup | null>(null);
  const mapAnchorLayerRef = useRef<L.LayerGroup | null>(null);
  const mapBoundaryLayerRef = useRef<L.LayerGroup | null>(null);
  const tileLayerRefs = useRef<L.TileLayer[]>([]);
  const displayedLevelIdRef = useRef<number | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [measurementPoints, setMeasurementPoints] = useState<MapPoint[]>([]);
  const [visibleBoundary, setVisibleBoundary] = useState<{
    name: string;
    kind: "administrative" | "guidance";
  } | null>(null);

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
    const measurementLayer = L.layerGroup().addTo(map);
    const mapBoundaryLayer = L.layerGroup().addTo(map);
    const mapAnchorLayer = L.layerGroup().addTo(map);
    mapRef.current = map;
    layerRef.current = layer;
    measurementLayerRef.current = measurementLayer;
    mapBoundaryLayerRef.current = mapBoundaryLayer;
    mapAnchorLayerRef.current = mapAnchorLayer;

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
      measurementLayerRef.current = null;
      mapAnchorLayerRef.current = null;
      mapBoundaryLayerRef.current = null;
      tileLayerRefs.current = [];
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map === null) {
      return;
    }
    tileLayerRefs.current.forEach((layer) => layer.remove());
    tileLayerRefs.current = tileUrls(mapStyle, mapLabels).map((tileUrl) =>
      L.tileLayer(tileUrl, readableTileOptions(tileUrl, mapLabels)).addTo(map),
    );
  }, [mapLabels, mapStyle]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = mapBoundaryLayerRef.current;
    if (map === null || layer === null) {
      return;
    }
    const currentMap = map;
    const currentLayer = layer;

    function renderMapBoundaries() {
      currentLayer.clearLayers();
      const zoom = currentMap.getZoom();
      const visibleBoundaries = mapAnchors.filter(
        (anchor) => anchor.boundary && zoom >= (anchor.boundaryMinZoom ?? 6),
      );
      const primaryBoundary = visibleBoundaries.reduce<DailyMapAnchor | undefined>(
        (current, anchor) =>
          current === undefined || anchor.minHintCount >= current.minHintCount ? anchor : current,
        undefined,
      );
      setVisibleBoundary(
        primaryBoundary
          ? {
              name: primaryBoundary.name,
              kind: primaryBoundary.boundaryKind ?? "administrative",
            }
          : null,
      );
      if (primaryBoundary?.boundary) {
        const isGuidanceArea = primaryBoundary.boundaryKind === "guidance";
        L.geoJSON(primaryBoundary.boundary as Parameters<typeof L.geoJSON>[0], {
          interactive: false,
          style: {
            color: isGuidanceArea ? "#2563eb" : "#087f73",
            dashArray: isGuidanceArea ? "6 8" : "9 7",
            fillColor: isGuidanceArea ? "#60a5fa" : "#10b981",
            fillOpacity: isGuidanceArea ? 0.08 : 0.06,
            opacity: isGuidanceArea ? 0.9 : 1,
            weight: isGuidanceArea ? 3 : 4,
          },
        }).addTo(currentLayer);
      }
    }

    renderMapBoundaries();
    currentMap.on("zoomend", renderMapBoundaries);
    return () => {
      currentMap.off("zoomend", renderMapBoundaries);
      currentLayer.clearLayers();
    };
  }, [mapAnchors]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = mapAnchorLayerRef.current;
    if (map === null || layer === null) {
      return;
    }
    const currentMap = map;
    const currentLayer = layer;

    function renderMapAnchors() {
      currentLayer.clearLayers();
      if (!mapLabels) {
        return;
      }
      const zoom = currentMap.getZoom();
      mapAnchors
        .filter((anchor) => zoom >= anchor.minZoom && zoom <= anchor.maxZoom)
        .forEach((anchor) => {
          L.marker([anchor.point.lat, anchor.point.lng], {
            icon: mapAnchorIcon(anchor.name),
            interactive: false,
            keyboard: false,
            zIndexOffset: 150,
          }).addTo(currentLayer);
        });
    }

    renderMapAnchors();
    currentMap.on("zoomend", renderMapAnchors);
    return () => {
      currentMap.off("zoomend", renderMapAnchors);
      currentLayer.clearLayers();
    };
  }, [mapAnchors, mapLabels]);

  useEffect(() => {
    const map = mapRef.current;
    if (map === null) {
      return undefined;
    }
    const currentMap = map;

    function handleClick(event: L.LeafletMouseEvent) {
      if (measuring) {
        const point = {
          lat: event.latlng.lat,
          lng: event.latlng.lng,
        };
        setMeasurementPoints((current) => (current.length === 1 ? [...current, point] : [point]));
        return;
      }
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
  }, [level.submitted, measuring, onMapPick]);

  useEffect(() => {
    const layer = measurementLayerRef.current;
    if (layer === null) {
      return;
    }
    layer.clearLayers();

    const positions = measurementPoints.map(
      (point) => [point.lat, point.lng] as L.LatLngTuple,
    );
    if (positions.length === 2) {
      L.polyline(positions, {
        color: "#111827",
        dashArray: "7 6",
        opacity: 0.9,
        weight: 4,
      }).addTo(layer);
    }
    positions.forEach((position, index) => {
      L.circleMarker(position, {
        color: "#ffffff",
        fillColor: index === 0 ? "#111827" : "#d71920",
        fillOpacity: 1,
        radius: 7,
        weight: 3,
      }).addTo(layer);
    });
  }, [measurementPoints]);

  const measuredDistance =
    measurementPoints.length === 2
      ? L.latLng(measurementPoints[0].lat, measurementPoints[0].lng).distanceTo(
          L.latLng(measurementPoints[1].lat, measurementPoints[1].lng),
        )
      : null;

  function toggleMeasurement() {
    setMeasuring((current) => !current);
    setMeasurementPoints([]);
  }

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (map === null || layer === null) {
      return;
    }

    const levelChanged = displayedLevelIdRef.current !== level.id;
    displayedLevelIdRef.current = level.id;
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

    if (levelChanged) {
      map.setView([25, 0], defaultMapZoom(), { animate: false });
    }
    return () => window.clearTimeout(resizeTimer);
  }, [acceptedSelection, draftSelection, level]);

  return (
    <div className="relative -mx-3 w-[calc(100%+1.5rem)] overflow-hidden border-y border-slate-200 bg-slate-100 min-[420px]:rounded-xl min-[420px]:border">
      <div
        ref={containerRef}
        className="h-[30rem] w-full min-[420px]:h-[34rem]"
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
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {(draftSelection.alternatives?.length ?? 0) > 1 ? (
              <>
                <button
                  type="button"
                  aria-label="Previous nearby place"
                  onClick={() => onCycleDraft(-1)}
                  disabled={submitting}
                  className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 saints-focus"
                >
                  <ChevronLeft aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
                </button>
                <button
                  type="button"
                  aria-label="Next nearby place"
                  onClick={() => onCycleDraft(1)}
                  disabled={submitting}
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
                disabled={submitting}
                className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 saints-focus"
              >
                <X aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
              </button>
              <button
                type="button"
                aria-label="Use selected place"
                onClick={onUseDraft}
                disabled={submitting}
                className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-black text-white shadow-sm saints-focus disabled:cursor-not-allowed disabled:bg-emerald-300"
              >
                {submitting ? (
                  <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin" />
                ) : (
                  <Check aria-hidden="true" className="h-5 w-5" strokeWidth={3} />
                )}
                Use this place
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {visibleBoundary ? (
        <div
          className={[
            "pointer-events-none absolute bottom-24 left-3 z-[700] inline-flex min-h-9 max-w-[calc(100%-5rem)] items-center gap-2 rounded-lg bg-white/95 px-3 text-xs font-black shadow-lg",
            visibleBoundary.kind === "guidance"
              ? "border border-blue-200 text-blue-800"
              : "border border-emerald-200 text-emerald-800",
          ].join(" ")}
        >
          <span
            aria-hidden="true"
            className={[
              "w-7 border-t-[3px] border-dashed",
              visibleBoundary.kind === "guidance" ? "border-blue-700" : "border-emerald-700",
            ].join(" ")}
          />
          <span className="truncate">
            {visibleBoundary.name} {visibleBoundary.kind === "guidance" ? "search area" : "boundary"}
          </span>
        </div>
      ) : null}
      <div className="pointer-events-none absolute bottom-10 left-3 z-[700] flex max-w-[calc(100%-5rem)] items-stretch gap-2">
        <button
          type="button"
          aria-label={measuring ? "Stop measuring distance" : "Measure distance"}
          aria-pressed={measuring}
          title={measuring ? "Stop measuring distance" : "Measure distance"}
          onClick={toggleMeasurement}
          disabled={snapLoading}
          className={[
            "pointer-events-auto inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-black shadow-lg saints-focus",
            measuring
              ? "border-slate-950 bg-slate-950 text-white"
              : "border-slate-200 bg-white text-slate-800",
            snapLoading ? "cursor-not-allowed opacity-50" : "",
          ].join(" ")}
        >
          <Ruler aria-hidden="true" className="h-5 w-5" strokeWidth={2.6} />
          <span>{measuring ? "Done" : "Measure"}</span>
        </button>
        {measuring ? (
          <div
            className="flex min-h-11 min-w-0 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-black text-slate-800 shadow-lg"
            aria-live="polite"
          >
            {measuredDistance !== null
              ? formatMeasuredDistance(measuredDistance)
              : measurementPoints.length === 1
                ? "Tap end"
                : "Tap start"}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function MapGame() {
  const { availableAnnouncements } = useAuth();
  const [searchParams] = useSearchParams();
  const requestedDate = searchParams.get("date")?.trim() || undefined;
  const [game, setGame] = useState<DailyMapGameResponse | null>(null);
  const [showPromoReplay, setShowPromoReplay] = useState(false);
  const mapPromoAvailable = availableAnnouncements.some(
    (announcement) => announcement.kind === "daily-map-promo",
  );
  const [selectedLevelId, setSelectedLevelId] = useState<number | null>(null);
  const [pendingSelections, setPendingSelections] = useState<Record<number, DailyMapSnapSelection>>({});
  const [draftSelection, setDraftSelection] = useState<DailyMapSnapSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectionNotice, setSelectionNotice] = useState("");
  const [snapLoading, setSnapLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const submitInFlightRef = useRef(false);
  const lockButtonRef = useRef<HTMLButtonElement | null>(null);
  const [mapLabels, setMapLabels] = useState(() => {
    try {
      return window.localStorage.getItem("fultons:daily-map:labels") !== "off";
    } catch {
      return true;
    }
  });
  const [mapStyle, setMapStyle] = useState<MapStyle>(() => {
    try {
      return window.localStorage.getItem("fultons:daily-map:style") === "detail"
        ? "detail"
        : "clear";
    } catch {
      return "clear";
    }
  });

  const loadGame = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.dailyMapGame(requestedDate);
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
  }, [requestedDate]);

  useEffect(() => {
    void loadGame();
  }, [loadGame]);

  useEffect(() => {
    setDraftSelection(null);
    setSelectionNotice("");
    setSnapLoading(false);
    setRevealing(false);
  }, [selectedLevelId]);

  useEffect(() => {
    try {
      window.localStorage.setItem("fultons:daily-map:labels", mapLabels ? "on" : "off");
    } catch {
      // The toggle still works for the current session if storage is unavailable.
    }
  }, [mapLabels]);

  useEffect(() => {
    try {
      window.localStorage.setItem("fultons:daily-map:style", mapStyle);
    } catch {
      // The toggle still works for the current session if storage is unavailable.
    }
  }, [mapStyle]);

  const levels = game?.levels ?? [];
  const selectedLevel = useMemo(
    () => levels.find((level) => level.id === selectedLevelId) ?? levels[0],
    [levels, selectedLevelId],
  );
  const pendingSelection = selectedLevel ? pendingSelections[selectedLevel.id] : undefined;
  const pendingPoint = pendingSelection?.point;
  const totalScore = levels.reduce((total, level) => total + (level.result?.score ?? 0), 0);
  const completed = levels.filter((level) => level.submitted).length;
  const currentRevealedHintCount = selectedLevel?.revealedHintCount ?? 0;
  const clues = selectedLevel?.clues ?? [];
  const visibleClues = clues;
  const nextClue = selectedLevel && !selectedLevel.submitted && currentRevealedHintCount < 3
    ? [
        { title: "Medium clue", maxPoints: 7 },
        { title: "Easy clue", maxPoints: 5 },
        { title: "Place name", maxPoints: 2 },
      ][currentRevealedHintCount]
    : undefined;
  const currentMaxPoints =
    selectedLevel?.result?.maxPoints ?? clues[clues.length - 1]?.maxPoints ?? 0;

  const pickPointForSelected = useCallback(
    async (point: MapPoint, zoom: number) => {
      if (
        selectedLevel === undefined ||
        selectedLevel.submitted ||
        snapLoading ||
        submitting ||
        revealing
      ) {
        return;
      }
      const levelId = selectedLevel.id;
      setSnapLoading(true);
      setError("");
      setSelectionNotice("");
      setDraftSelection(null);
      setPendingSelections((current) => {
        const next = { ...current };
        delete next[levelId];
        return next;
      });
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
    [loadGame, revealing, selectedLevel, snapLoading, submitting],
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

  const submitSelectedGuess = useCallback(
    async (selection: DailyMapSnapSelection | undefined) => {
      if (
        selectedLevel === undefined ||
        selection === undefined ||
        selectedLevel.submitted ||
        submitInFlightRef.current ||
        submitting ||
        revealing
      ) {
        return;
      }
      submitInFlightRef.current = true;
      setSubmitting(true);
      setError("");
      setSelectionNotice("");
      try {
        const response = await api.submitDailyMapGuess(
          selectedLevel.id,
          selection.selectionId,
        );
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
                ? {
                    ...level,
                    submitted: true,
                    revealedHintCount: response.result.revealedHintCount,
                    result: response.result,
                  }
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
        submitInFlightRef.current = false;
        setSubmitting(false);
      }
    },
    [revealing, selectedLevel, submitting],
  );

  const revealNextClue = useCallback(async () => {
    if (
      selectedLevel === undefined ||
      selectedLevel.submitted ||
      selectedLevel.revealedHintCount >= 3 ||
      revealing ||
      submitting
    ) {
      return;
    }
    setRevealing(true);
    setError("");
    try {
      const response = await api.revealDailyMapClue(
        selectedLevel.id,
        selectedLevel.revealedHintCount,
      );
      setGame((current) =>
        current === null
          ? current
          : {
              ...current,
              levels: current.levels.map((level) =>
                level.id === selectedLevel.id ? response.level : level,
              ),
            },
      );
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Clue reveal failed.");
    } finally {
      setRevealing(false);
    }
  }, [revealing, selectedLevel, submitting]);

  const useDraftSelection = useCallback(() => {
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
    <>
      {showPromoReplay && mapPromoAvailable ? (
        <MapGamePromo
          primaryLabel="Back to map"
          onDismiss={() => setShowPromoReplay(false)}
          onPlay={() => setShowPromoReplay(false)}
        />
      ) : null}
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
            <div className="flex shrink-0 items-stretch gap-2">
              {mapPromoAvailable ? (
                <button
                  type="button"
                  onClick={() => setShowPromoReplay(true)}
                  className="saints-focus flex h-12 w-14 flex-col items-center justify-center rounded-lg bg-white/10 text-white transition hover:bg-white/15"
                  aria-label="Replay map introduction"
                  title="Replay map introduction"
                >
                  <PlayCircle aria-hidden="true" className="h-5 w-5" strokeWidth={2.6} />
                  <span className="mt-0.5 text-[0.58rem] font-black uppercase">Intro</span>
                </button>
              ) : null}
              <div className="rounded-lg bg-white/10 px-3 py-2 text-right">
                <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
                  {shortDate(game.date)}
                </p>
                <p className="mt-0.5 text-xl font-black leading-none">
                  {totalScore}
                  <span className="text-sm text-white/55">/{game.maxScore}</span>
                </p>
              </div>
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
          <div className="grid grid-cols-2 gap-2">
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
            <div
              className="grid grid-cols-2 rounded-lg border border-slate-200 bg-slate-50 p-1"
              role="group"
              aria-label="Map style"
            >
              {(["clear", "detail"] as const).map((style) => (
                <button
                  key={style}
                  type="button"
                  aria-pressed={mapStyle === style}
                  onClick={() => setMapStyle(style)}
                  className={[
                    "flex min-h-9 items-center justify-center gap-1 rounded-md px-2 text-sm font-black leading-none transition saints-focus",
                    mapStyle === style
                      ? "bg-slate-950 text-white shadow-sm"
                      : "text-slate-500",
                  ].join(" ")}
                >
                  <Layers aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
                  <span>{style === "clear" ? "Street" : "Terrain"}</span>
                </button>
              ))}
            </div>
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
                onClick={() => void revealNextClue()}
                disabled={revealing || submitting}
                className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-black text-slate-700 transition hover:border-saints-red/40 saints-focus"
              >
                {revealing ? "Revealing clue" : `Reveal ${nextClue.title.toLowerCase()} - max ${nextClue.maxPoints} pts`}
              </button>
            ) : null}
          </div>

          <MapCanvas
            key={selectedLevel.id}
            level={selectedLevel}
            mapLabels={mapLabels}
            mapStyle={mapStyle}
            mapAnchors={selectedLevel.mapAnchors ?? []}
            acceptedSelection={pendingSelection}
            draftSelection={draftSelection}
            selectionNotice={selectionNotice}
            snapLoading={snapLoading}
            submitting={submitting}
            onMapPick={pickPointForSelected}
            onUseDraft={useDraftSelection}
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
                onClick={() => void submitSelectedGuess(pendingSelection)}
                disabled={pendingPoint === undefined || draftSelection !== null || snapLoading || submitting || revealing}
                className={[
                  "inline-flex min-h-12 min-w-[8.5rem] items-center justify-center gap-2 rounded-lg px-4 text-sm font-black transition saints-focus",
                  pendingPoint === undefined || draftSelection !== null || snapLoading || submitting || revealing
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
    </>
  );
}

function ResultPanel({ result }: { result: DailyMapGameResult }) {
  const cluesSeen = result.revealedHintCount + 1;
  const solvingStage = result.revealedHintCount === 0
    ? "the hard clue"
    : result.revealedHintCount === 1
      ? "the medium clue"
      : result.revealedHintCount === 2
        ? "the easy clue"
        : "the place name";
  const progressSummary = result.correct
    ? result.revealedHintCount >= 3
      ? "You completed the round after revealing the place name."
      : `You solved it after seeing ${solvingStage}.`
    : `Your selected place was outside the answer area after seeing ${solvingStage}.`;

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
      <div className="grid grid-cols-3 gap-2 text-center">
        <ResultMetric label="Score" value={`${result.score}`} icon={<Trophy className="h-4 w-4" />} />
        <ResultMetric label="Result" value={result.correct ? "Correct" : "Wrong"} />
        <ResultMetric label="Clues seen" value={`${cluesSeen}`} />
      </div>
      <div className="mt-3 border-t border-slate-200 pt-3">
        <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
          Correct answer
        </p>
        <p className="mt-1 text-xl font-black leading-tight text-slate-950">
          {result.place.name}
        </p>
        {result.selectedPlace.name && result.selectedPlace.name !== result.place.name ? (
          <p className="mt-1 text-sm font-black text-slate-700">
            You selected {result.selectedPlace.name}
          </p>
        ) : null}
        <p className="mt-2 text-sm font-black leading-snug text-slate-700">{progressSummary}</p>
        <p className="mt-2 text-sm font-semibold leading-snug text-slate-600">
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
