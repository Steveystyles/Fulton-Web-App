import { Easing, interpolate, spring } from "remotion";

export const snappyEase = Easing.bezier(0.16, 1, 0.3, 1);
export const thumpEase = Easing.bezier(0.2, 0.8, 0.2, 1);

export function clampFrame(frame: number, start: number, end: number) {
  return Math.min(Math.max(frame, start), end);
}

export function fadeIn(frame: number, start: number, end: number) {
  return interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: snappyEase,
  });
}

export function slideUp(frame: number, start: number, end: number, distance: number) {
  return interpolate(frame, [start, end], [distance, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: snappyEase,
  });
}

export function popSpring(frame: number, fps: number, delay = 0, damping = 12) {
  return spring({
    frame: Math.max(0, frame - delay),
    fps,
    config: {
      damping,
      mass: 0.9,
      stiffness: 150,
    },
  });
}

export function impactShake(frame: number, impactFrame: number, amplitude: number) {
  const age = frame - impactFrame;
  if (age < 0 || age > 16) {
    return 0;
  }

  const falloff = interpolate(age, [0, 16], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return Math.sin(age * 2.7) * amplitude * falloff;
}

export function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}
