import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Soundtrack } from "./components/Soundtrack";
import { defaultGamePromoData } from "./data/defaultGamePromoData";
import { compositionDefinitions } from "./Root";
import { getLayoutMetrics } from "./utils/layout";
import { DURATION_IN_FRAMES, sceneRanges } from "./utils/timing";
import {
  fitClueTextSize,
  requiredScores,
  validateGamePromoData,
  validateSceneTimings,
} from "./utils/validation";

describe("map game promo data", () => {
  it("requires four clues", () => {
    expect(defaultGamePromoData.clues).toHaveLength(4);
    expect(() => validateGamePromoData(defaultGamePromoData)).not.toThrow();
  });

  it("uses the default score sequence", () => {
    expect(defaultGamePromoData.clues.map((clue) => clue.points)).toEqual([...requiredScores]);
  });

  it("uses the fourth clue as the answer reveal", () => {
    expect(defaultGamePromoData.clues[3]?.text).toBe(defaultGamePromoData.locationName);
  });
});

describe("map game promo timing and compositions", () => {
  it("keeps every scene within the total duration", () => {
    expect(() => validateSceneTimings()).not.toThrow();
    expect(sceneRanges.every((range) => range.start >= 0 && range.end < DURATION_IN_FRAMES)).toBe(true);
  });

  it("registers landscape, square, and vertical compositions", () => {
    expect(compositionDefinitions.map((composition) => composition.id)).toEqual([
      "MapGamePromo",
      "MapGamePromoSquare",
      "MapGamePromoVertical",
    ]);
  });

  it("uses adapted dimensions for each composition", () => {
    expect(compositionDefinitions.map(({ width, height }) => `${width}x${height}`)).toEqual([
      "1920x1080",
      "1080x1080",
      "1080x1920",
    ]);
  });
});

describe("map game promo layout safeguards", () => {
  it("reduces long clue text size before it can crowd the card", () => {
    const longText =
      "This capital sits in a valley surrounded by Himalayan peaks, ancient temples, busy markets, and a lot of very confident guesses.";
    expect(fitClueTextSize(longText, 43, 30)).toBeLessThan(43);
    expect(fitClueTextSize(longText, 43, 30)).toBeGreaterThanOrEqual(30);
  });

  it("keeps responsive safe areas and readable headline sizes", () => {
    const landscape = getLayoutMetrics(1920, 1080, "landscape");
    const square = getLayoutMetrics(1080, 1080, "square");
    const vertical = getLayoutMetrics(1080, 1920, "vertical");

    expect(landscape.safeX).toBeGreaterThanOrEqual(80);
    expect(square.safeX).toBeGreaterThanOrEqual(80);
    expect(vertical.safeY).toBeGreaterThanOrEqual(100);
    expect(Math.min(landscape.headline, square.headline, vertical.headline)).toBeGreaterThanOrEqual(84);
  });

  it("does not render audio tags when audio is disabled", () => {
    const markup = renderToStaticMarkup(
      <Soundtrack audioSettings={{ enabled: false, musicVolume: 0.2, effectsVolume: 0.4 }} />,
    );

    expect(markup).toBe("");
  });
});
