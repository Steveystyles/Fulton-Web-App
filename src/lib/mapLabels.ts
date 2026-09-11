export type MapLabelCandidate = {
  id: number;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  priority: number;
};

export type LabelBox = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

const INSET = 8;
const GAP = 6;
const MAX_LABELS = 6;

function normalizedName(name: string): string {
  return name.trim().replace(/\s+/gu, " ").toLowerCase();
}

function validBox(box: LabelBox): boolean {
  return [box.left, box.top, box.right, box.bottom].every(Number.isFinite)
    && box.right > box.left && box.bottom > box.top;
}

function tooClose(a: LabelBox, b: LabelBox): boolean {
  return a.left < b.right + GAP && a.right > b.left - GAP
    && a.top < b.bottom + GAP && a.bottom > b.top - GAP;
}

/**
 * Lay out measured labels in map-container pixels, without moving their anchors.
 * Reserve marker/control bounds separately. Hidden labels can be reconsidered
 * after a zoom or pan; squeezing or pushing them across the map is avoided.
 */
export function layoutMapLabels(
  candidates: MapLabelCandidate[],
  viewport: { width: number; height: number },
  reserved: LabelBox[] = [],
): Array<MapLabelCandidate & { left: number; top: number }> {
  if (!Number.isFinite(viewport.width) || !Number.isFinite(viewport.height)
    || viewport.width <= INSET * 2 || viewport.height <= INSET * 2) return [];

  const sorted = candidates.filter((candidate) => (
    typeof candidate.name === "string" && normalizedName(candidate.name).length > 0
    && [candidate.id, candidate.x, candidate.y, candidate.width, candidate.height, candidate.priority].every(Number.isFinite)
    && candidate.width > 0 && candidate.height > 0
    && candidate.x >= 0 && candidate.x <= viewport.width
    && candidate.y >= 0 && candidate.y <= viewport.height
  )).sort((a, b) => b.priority - a.priority || a.id - b.id
    || a.x - b.x || a.y - b.y || a.width - b.width || a.height - b.height);

  const names = new Set<string>();
  const occupied = reserved.filter(validBox);
  const placed: Array<MapLabelCandidate & { left: number; top: number }> = [];

  for (const candidate of sorted) {
    const name = normalizedName(candidate.name);
    if (names.has(name)) continue;
    names.add(name);

    const { x, y, width, height } = candidate;
    // Two nearby offsets permit a small adjustment around controls/markers,
    // but never detach a label from the place it describes.
    const positions = [18, 26].flatMap((offset) => [
      { left: x - width / 2, top: y - height - offset },
      { left: x - width / 2, top: y + offset },
      { left: x + offset, top: y - height / 2 },
      { left: x - width - offset, top: y - height / 2 },
    ]);

    for (const position of positions) {
      const box = { ...position, right: position.left + width, bottom: position.top + height };
      if (box.left < INSET || box.top < INSET
        || box.right > viewport.width - INSET || box.bottom > viewport.height - INSET
        || occupied.some((other) => tooClose(box, other))) continue;

      placed.push({ ...candidate, ...position });
      occupied.push(box);
      break;
    }
    if (placed.length === MAX_LABELS) break;
  }

  return placed;
}
