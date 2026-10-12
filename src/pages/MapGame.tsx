import { HelpButton } from "../components/HelpButton";
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import {
  Check,
  CircleAlert,
  LoaderCircle,
  Layers,
  MapPinned,
  Maximize2,
  Minimize2,
  RotateCcw,
  Ruler,
  Trophy,
  Type,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Card } from "../components/Card";
import { DailyJourney } from "../components/DailyJourney";
import { GameFeedback } from "../components/GameFeedback";
import { layoutMapLabels, type LabelBox } from "../lib/mapLabels";
import { useAuth } from "../context/AuthContext";
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

function mapAnchorIcon(name: string, width: number, height: number, offsetX: number, offsetY: number) {
  return L.divIcon({
    className: "daily-map-search-anchor",
    html: `<span>${escapedMapLabel(name)}</span>`,
    iconSize: [width, height],
    iconAnchor: [-offsetX, -offsetY],
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
  draftSelection: DailyMapSnapSelection | null;
  selectionNotice: string;
  snapLoading: boolean;
  revealing: boolean;
  submitting: boolean;
  onMapPick: (point: MapPoint, zoom: number) => void;
  onUseDraft: () => void;
  onRejectDraft: () => void;
  onCycleDraft: (direction: -1 | 1) => void;
  onDismissSelectionNotice: () => void;
  helpControl: ReactNode;
};

function MapCanvas({
  level,
  mapLabels,
  mapStyle,
  mapAnchors,
  draftSelection,
  selectionNotice,
  snapLoading,
  revealing,
  submitting,
  onMapPick,
  onUseDraft,
  onRejectDraft,
  onCycleDraft,
  onDismissSelectionNotice,
  helpControl,
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
  const [expanded, setExpanded] = useState(false);
  const selectionBusy = snapLoading || submitting || revealing;
  const selectionPanelRef = useRef<HTMLDivElement>(null);
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
    const resizeObserver = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resizeObserver.observe(containerRef.current);

    return () => {
      window.clearTimeout(resizeTimer);
      resizeObserver.disconnect();
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
      const size = currentMap.getSize();
      const reserved: LabelBox[] = [{ left: size.x - 58, top: size.y - 122, right: size.x, bottom: size.y }];
      const activePin = draftSelection;
      const pins = level.result
        ? [level.result.answerPoint, level.result.guessedPoint]
        : activePin ? [activePin.point] : [];
      for (const pin of pins) {
        const point = currentMap.latLngToContainerPoint([pin.lat, pin.lng]);
        reserved.push({ left: point.x - 20, top: point.y - 20, right: point.x + 20, bottom: point.y + 20 });
      }
      const textContext = document.createElement("canvas").getContext("2d");
      if (textContext) textContext.font = "800 13px system-ui";
      const candidates = mapAnchors.flatMap((anchor, id) => {
        if (zoom < anchor.minZoom || zoom > anchor.maxZoom) return [];
        const point = currentMap.latLngToContainerPoint([anchor.point.lat, anchor.point.lng]);
        return [{ id, name: anchor.name, x: point.x, y: point.y,
          width: Math.ceil(textContext?.measureText(anchor.name).width ?? anchor.name.length * 8) + 12,
          height: 24, priority: anchor.minHintCount }];
      });
      layoutMapLabels(candidates, { width: size.x, height: size.y }, reserved)
        .forEach((label) => {
          const anchor = mapAnchors[label.id];
          L.marker([anchor.point.lat, anchor.point.lng], {
            icon: mapAnchorIcon(anchor.name, label.width, label.height, label.left - label.x, label.top - label.y),
            interactive: false,
            keyboard: false,
            zIndexOffset: 150,
          }).addTo(currentLayer);
        });
    }

    renderMapAnchors();
    currentMap.on("moveend zoomend resize", renderMapAnchors);
    return () => {
      currentMap.off("moveend zoomend resize", renderMapAnchors);
      currentLayer.clearLayers();
    };
  }, [mapAnchors, mapLabels, level.result, draftSelection]);

  useEffect(() => {
    if (!draftSelection) return;
    selectionPanelRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [draftSelection?.selectionId]);

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

    const activeSelection = draftSelection;
    if (activeSelection !== undefined && activeSelection !== null) {
      const point: L.LatLngTuple = [activeSelection.point.lat, activeSelection.point.lng];
      L.marker(point, {
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
  }, [draftSelection, level]);

  return (
    <div className="map-canvas min-w-0 space-y-2">
      <div className="map-viewport relative isolate overflow-hidden rounded-xl border border-slate-200 bg-slate-100" data-expanded={expanded}>
      <div
        ref={containerRef}
        className="map-stage w-full"
        aria-label={`${level.title} guessing map`}
        aria-describedby="map-keyboard-help"
      />
      <p id="map-keyboard-help" className="sr-only">Focus the map and use arrow keys to move, plus and minus to zoom. Then use the Use centre button below the map to review a nearby place. Locking a place is final.</p>
      {!level.submitted && !measuring ? <>
        <span aria-hidden="true" className="map-crosshair pointer-events-none absolute left-1/2 top-1/2 z-600 flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white bg-black/70 text-white"><svg viewBox="0 0 24 24" className="block h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg></span>
      </> : null}
      </div>
      {draftSelection === null ? <div className="map-tools" data-tool-count={level.submitted ? 3 : 4} role="group" aria-label="Map tools">
        {!level.submitted ? <button type="button" aria-label="Use map centre to choose a place" disabled={selectionBusy || measuring} className="map-tool saints-focus" onClick={() => {
          const map = mapRef.current;
          if (map) { const centre = map.getCenter(); onMapPick({ lat: centre.lat, lng: centre.lng }, map.getZoom()); }
        }}><MapPinned aria-hidden="true" className="h-4 w-4 shrink-0" /><span className="map-tool__full-label">Use centre</span><span className="map-tool__short-label">Pick centre</span></button> : null}
        <button type="button" aria-label={measuring ? "Stop measuring distance" : "Measure distance"} aria-pressed={measuring} onClick={toggleMeasurement} disabled={selectionBusy} className="map-tool saints-focus">
          <Ruler aria-hidden="true" className="h-4 w-4 shrink-0" /><span>{measuring ? "Done" : "Measure"}</span>
        </button>
        <button type="button" aria-label={expanded ? "Reduce map height" : "Enlarge map"} aria-pressed={expanded} onClick={() => setExpanded(current => !current)} className="map-tool saints-focus">
          {expanded ? <Minimize2 aria-hidden="true" className="h-4 w-4 shrink-0" /> : <Maximize2 aria-hidden="true" className="h-4 w-4 shrink-0" />}<span className="map-tool__full-label">{expanded ? "Smaller" : "Larger map"}</span><span className="map-tool__short-label">{expanded ? "Shrink" : "Expand"}</span>
        </button>
        {helpControl}
      </div> : null}
      {measuring ? <p role="status" className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-bold text-slate-800">
        {measuredDistance !== null ? `Distance: ${formatMeasuredDistance(measuredDistance)}. Tap to start a new measurement.` : measurementPoints.length === 1 ? "Tap the end point on the map." : "Tap the start point on the map."}
      </p> : null}
      {snapLoading ? (
        <div role="status" className="flex min-h-11 items-center gap-2 rounded-lg bg-slate-100 px-3 text-sm font-bold text-slate-700">
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin text-saints-red" />
          Finding place
        </div>
      ) : null}
      {selectionNotice && !snapLoading && !level.submitted ? (
        <div
          className="flex min-w-0 items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-2 text-amber-950"
          aria-live="polite"
        >
          <CircleAlert aria-hidden="true" className="h-5 w-5 shrink-0 text-amber-600" strokeWidth={2.6} />
          <p className="min-w-0 flex-1 text-sm font-black leading-snug">{selectionNotice}{draftSelection ? " Your previous pin has been kept; this tap did not select a new place." : ""}</p>
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
          ref={selectionPanelRef}
          className="map-pin-review min-w-0 rounded-xl border border-slate-200 bg-white p-2.5"
          aria-live="polite"
        >
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-saints-red">
                {draftSelection.snapped ? "Selected place" : "Selected point"}
                {(draftSelection.alternatives?.length ?? 0) > 1
                  ? ` · ${(draftSelection.selectedIndex ?? 0) + 1} of ${draftSelection.alternatives?.length} nearby`
                  : ""}
              </p>
              <p className="mt-0.5 text-base font-black leading-tight text-slate-950 wrap-anywhere">
                {draftSelection.name}
              </p>
              {draftSelection.admin1 || draftSelection.countryCode ? (
                <p className="mt-0.5 wrap-break-word text-xs font-bold leading-snug text-slate-500">
                  {[draftSelection.admin1, draftSelection.countryCode].filter(Boolean).join(", ")}
                </p>
              ) : null}
            </div>
            {(draftSelection.alternatives?.length ?? 0) > 1 ? (
              <div className="flex shrink-0 gap-1" role="group" aria-label="Nearby places">
                <button
                  type="button"
                  aria-label="Previous nearby place"
                  onClick={() => onCycleDraft(-1)}
                  disabled={selectionBusy}
                  className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-800 saints-focus disabled:opacity-50"
                >
                  <span aria-hidden="true" className="text-xl font-black leading-none">←</span>
                </button>
                <button
                  type="button"
                  aria-label="Next nearby place"
                  onClick={() => onCycleDraft(1)}
                  disabled={selectionBusy}
                  className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-800 saints-focus disabled:opacity-50"
                >
                  <span aria-hidden="true" className="text-xl font-black leading-none">→</span>
                </button>
              </div>
            ) : null}
          </div>
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1.45fr)] gap-2">
              <button
                type="button"
                aria-label="Change selected place"
                onClick={onRejectDraft}
                disabled={selectionBusy}
                className="inline-flex min-h-11 min-w-0 items-center justify-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-sm font-black text-slate-700 saints-focus"
              >
                <X aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={3} />
                <span>Change pin</span>
              </button>
              <button
                type="button"
                aria-label={`Lock ${draftSelection.name} for ${level.clues[level.clues.length - 1]?.maxPoints ?? 0} points`}
                onClick={onUseDraft}
                disabled={selectionBusy}
                className="inline-flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-lg bg-saints-red px-3 py-2 text-sm font-black text-white saints-focus disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? (
                  <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin" />
                ) : (
                  <Check aria-hidden="true" className="h-5 w-5" strokeWidth={3} />
                )}
                <span>Lock for {level.clues[level.clues.length - 1]?.maxPoints ?? 0} pts</span>
              </button>
          </div>
        </div>
      ) : null}
      {visibleBoundary ? (
        <div
          className={[
            "flex min-w-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold",
            visibleBoundary.kind === "guidance"
              ? "border border-blue-200 text-blue-800"
              : "border border-emerald-200 text-emerald-800",
          ].join(" ")}
        >
          <span
            aria-hidden="true"
            className={[
              "w-5 shrink-0 border-t-[3px] border-dashed",
              visibleBoundary.kind === "guidance" ? "border-blue-700" : "border-emerald-700",
            ].join(" ")}
          />
          <span className="min-w-0 wrap-anywhere">
            {visibleBoundary.name} {visibleBoundary.kind === "guidance" ? "search area" : "boundary"}
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function MapGame() {
  const [searchParams] = useSearchParams();
  const requestedDate = searchParams.get("date")?.trim() || undefined;
  const [game, setGame] = useState<DailyMapGameResponse | null>(null);
  const [selectedLevelId, setSelectedLevelId] = useState<number | null>(null);
  const [draftSelection, setDraftSelection] = useState<DailyMapSnapSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectionNotice, setSelectionNotice] = useState("");
  const [snapLoading, setSnapLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const submitInFlightRef = useRef(false);
  const mapSectionRef = useRef<HTMLElement | null>(null);
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

  useEffect(() => {
    const section = mapSectionRef.current;
    const stage = section?.querySelector<HTMLElement>(".map-stage");
    if (!section || !stage) return;
    const navigation = document.querySelector<HTMLElement>('[aria-label="Game navigation"]');
    const header = document.querySelector<HTMLElement>(".top-shell");
    let frame = 0;
    const fit = () => {
      if (window.innerWidth >= 760) {
        stage.style.removeProperty("--map-fit-height");
        return;
      }
      // Keep the controls in view as clues, pin review, or an inline notice
      // changes height. The larger-map toggle remains an intentional scroll mode.
      const sectionRect = section.getBoundingClientRect();
      // A selected pin can scroll into view. Use the section's page position,
      // otherwise that scroll makes the map grow and pushes the review/nav away.
      const sectionTop = sectionRect.top + window.scrollY;
      const stageHeight = stage.getBoundingClientRect().height;
      const otherHeight = sectionRect.height - stageHeight;
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
      const navigationHeight = navigation?.getBoundingClientRect().height ?? 0;
      const available = Math.floor(viewportHeight - sectionTop - navigationHeight - otherHeight - 24);
      const next = `${Math.max(120, available)}px`;
      if (stage.style.getPropertyValue("--map-fit-height") !== next) {
        stage.style.setProperty("--map-fit-height", next);
      }
    };
    const scheduleFit = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(fit);
    };
    const observer = new ResizeObserver(scheduleFit);
    observer.observe(section);
    if (navigation) observer.observe(navigation);
    if (header) observer.observe(header);
    window.addEventListener("resize", scheduleFit);
    window.visualViewport?.addEventListener("resize", scheduleFit);
    scheduleFit();
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", scheduleFit);
      window.visualViewport?.removeEventListener("resize", scheduleFit);
      stage.style.removeProperty("--map-fit-height");
    };
  }, [game?.date, selectedLevel?.id]);

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
      // Keep the previous valid selection until a replacement lookup succeeds.
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
          if (caughtError.status === 404 && caughtError.message.includes("map round")) {
            setSelectionNotice("A new Map round is ready. Try another tap.");
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
        snapLoading ||
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
        setDraftSelection(null);
      } catch (caughtError) {
        setError(caughtError instanceof Error ? caughtError.message : "Guess failed to submit.");
      } finally {
        submitInFlightRef.current = false;
        setSubmitting(false);
      }
    },
    [revealing, selectedLevel, snapLoading, submitting],
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
    void submitSelectedGuess(draftSelection);
  }, [draftSelection, selectedLevel, submitSelectedGuess]);

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
            The current Map round could not be loaded.
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
      <section ref={mapSectionRef} className="min-w-0 space-y-3 pb-2" aria-label="Daily map game">
      <h1 className="sr-only">Map</h1>
      <Card className="map-game-card p-0">
        <div className="min-w-0 space-y-3 p-2 sm:p-3">
          <div className="map-play-layout">
          <div className="map-clues space-y-2" aria-label="Map game clues">
            {visibleClues.slice(-1).map((clue) => (
              <div
                key={clue.id}
                className={[
                  "min-w-0 rounded-xl border px-3 py-2",
                  clue.revealsName
                    ? "border-saints-red/25 bg-red-50"
                    : "border-slate-200 bg-slate-50",
                ].join(" ")}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                    {clue.title}
                  </p>
                  <p className="shrink-0 text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
                    Max {clue.maxPoints} pts
                  </p>
                </div>
                <p className="mt-1 text-base font-bold leading-snug text-slate-950 wrap-anywhere">
                  {clue.text}
                </p>
              </div>
            ))}
            {visibleClues.length > 1 ? <details className="min-w-0 text-sm"><summary className="min-h-11 cursor-pointer rounded-lg border bg-white p-2 font-bold saints-focus">Previous clues ({visibleClues.length - 1})</summary><div className="mt-2 space-y-3 rounded-xl border bg-white p-3">{visibleClues.slice(0, -1).map(clue => <div key={clue.id}><p className="font-black text-saints-red">{clue.title}</p><p className="mt-1 leading-relaxed">{clue.text}</p></div>)}</div></details> : null}
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
            draftSelection={draftSelection}
            selectionNotice={selectionNotice}
            snapLoading={snapLoading}
            revealing={revealing}
            submitting={submitting || snapLoading || revealing}
            onMapPick={pickPointForSelected}
            onUseDraft={useDraftSelection}
            onRejectDraft={rejectDraftSelection}
            onCycleDraft={cycleDraftSelection}
            onDismissSelectionNotice={dismissSelectionNotice}
            helpControl={<HelpButton title="How to play & map options" compact>
              <p className="my-3 leading-relaxed">Read the clue, tap the map or select its centre, then check the named place. Choose Lock only when you're sure — it is your final answer. More clues reduce the available points: 10 → 7 → 5 → 2. Zoom in and tap close to the named town, city or landmark, not just its country. Snapping is deliberately precise. After locking, we'll show the accepted answer area.</p>
              <div className="grid min-w-0 gap-2 min-[380px]:grid-cols-2">
                <button type="button" aria-pressed={mapLabels} aria-label={mapLabels ? "Turn map text off" : "Turn map text on"}
                  onClick={() => setMapLabels((current) => !current)}
                  className={`flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-base font-black saints-focus ${mapLabels ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-500"}`}>
                  <Type aria-hidden="true" className="h-4 w-4" strokeWidth={2.6} />
                  <span>{mapLabels ? "Map text on" : "Map text off"}</span>
                </button>
                <div className="grid grid-cols-2 rounded-lg border border-slate-200 bg-slate-50 p-1" role="group" aria-label="Map style">
                  {(["clear", "detail"] as const).map((style) => (
                    <button key={style} type="button" aria-pressed={mapStyle === style} onClick={() => setMapStyle(style)}
                      className={`flex min-h-11 min-w-0 items-center justify-center gap-1 rounded-md px-2 text-sm font-black saints-focus ${mapStyle === style ? "bg-slate-950 text-white shadow-sm" : "text-slate-500"}`}>
                      <Layers aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
                      <span>{style === "clear" ? "Street" : "Terrain"}</span>
                    </button>
                  ))}
                </div>
              </div>
            </HelpButton>}
          />

          {selectedLevel.result ? (
            <div className="map-result"><ResultPanel result={selectedLevel.result} date={game.date} showFeedback={levels.every(level => level.result !== undefined)} /></div>
          ) : null}
          </div>

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

function ResultPanel({ result, date, showFeedback }: { result: DailyMapGameResult; date: string; showFeedback: boolean }) {
  const { user } = useAuth();
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
    : `Not quite this time. Your pin was ${result.distanceFromCentreMeters < 1000 ? `${Math.round(result.distanceFromCentreMeters)} m` : `${(result.distanceFromCentreMeters / 1000).toFixed(1)} km`} from the target centre. The accepted area extends ${result.targetRadiusMeters < 1000 ? `${result.targetRadiusMeters} m` : `${(result.targetRadiusMeters / 1000).toFixed(1)} km`} from it.`;

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
      <div className="grid grid-cols-3 gap-2 text-center">
        <ResultMetric label="Score" value={`${result.score}`} icon={<Trophy className="h-4 w-4" />} />
        <ResultMetric label="Result" value={result.correct ? "Found it!" : "Missed"} />
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
        {showFeedback ? <GameFeedback game="map" /> : null}
        {user ? <DailyJourney current="map" summary={`Fulton's Quiz · ${date}\nPin the place: ${result.correct ? "Found it" : "A new place discovered"} · ${result.score} points · ${cluesSeen} clues`} /> : null}
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
        <p className="wrap-break-word text-lg font-black leading-tight text-slate-950">{value}</p>
      </div>
      <p className="mt-1 text-[0.62rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
    </div>
  );
}
