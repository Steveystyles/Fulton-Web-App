export const FPS = 30;
export const DURATION_IN_FRAMES = 810;

export const sceneTimings = {
  intro: { start: 0, duration: 90 },
  explorer: { start: 90, duration: 60 },
  clues: { start: 150, duration: 270 },
  mapGuess: { start: 420, duration: 180 },
  scoring: { start: 600, duration: 120 },
  finalCta: { start: 720, duration: 90 },
} as const;

export type SceneName = keyof typeof sceneTimings;

export const sceneRanges = Object.entries(sceneTimings).map(([name, timing]) => ({
  name,
  start: timing.start,
  end: timing.start + timing.duration - 1,
}));
