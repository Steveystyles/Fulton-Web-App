import type { GamePromoData } from "../data/defaultGamePromoData";
import { DURATION_IN_FRAMES, sceneRanges } from "./timing";

export const requiredScores = [10, 7, 5, 2] as const;

export function normalizeAnswer(value: string) {
  return value.trim().toLocaleLowerCase("en-GB");
}

export function validateGamePromoData(data: GamePromoData) {
  if (data.clues.length !== 4) {
    throw new Error("MapGamePromo requires exactly four clues.");
  }

  data.clues.forEach((clue, index) => {
    if (clue.points !== requiredScores[index]) {
      throw new Error(
        `Clue ${index + 1} must be worth ${requiredScores[index]} points.`,
      );
    }
  });

  const answerClue = data.clues[3]?.text ?? "";
  if (normalizeAnswer(answerClue) !== normalizeAnswer(data.locationName)) {
    throw new Error("The fourth clue must match the location name answer reveal.");
  }
}

export function validateSceneTimings() {
  for (const range of sceneRanges) {
    if (range.start < 0 || range.end >= DURATION_IN_FRAMES) {
      throw new Error(`${range.name} exceeds the composition duration.`);
    }
  }
}

export function fitClueTextSize(text: string, baseSize: number, minSize: number) {
  if (text.length <= 58) {
    return baseSize;
  }

  const reduction = Math.ceil((text.length - 58) / 12) * 4;
  return Math.max(minSize, baseSize - reduction);
}
