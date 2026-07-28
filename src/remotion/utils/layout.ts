import type { CSSProperties } from "react";

export type PromoFormat = "landscape" | "square" | "vertical";

export type LayoutMetrics = {
  format: PromoFormat;
  width: number;
  height: number;
  isLandscape: boolean;
  isSquare: boolean;
  isVertical: boolean;
  safeX: number;
  safeY: number;
  headline: number;
  subhead: number;
  body: number;
  label: number;
};

export function getLayoutMetrics(width: number, height: number, format: PromoFormat): LayoutMetrics {
  const minSide = Math.min(width, height);
  const isLandscape = format === "landscape";
  const isSquare = format === "square";
  const isVertical = format === "vertical";

  return {
    format,
    width,
    height,
    isLandscape,
    isSquare,
    isVertical,
    safeX: Math.round(isLandscape ? width * 0.07 : minSide * 0.08),
    safeY: Math.round(isVertical ? height * 0.055 : height * 0.08),
    headline: Math.round(isLandscape ? 122 : isVertical ? 88 : 92),
    subhead: Math.round(isLandscape ? 58 : isVertical ? 46 : 48),
    body: Math.round(isLandscape ? 42 : isVertical ? 36 : 36),
    label: Math.round(isLandscape ? 30 : 26),
  };
}

export function safeAreaStyle(metrics: LayoutMetrics): CSSProperties {
  return {
    position: "absolute",
    inset: `${metrics.safeY}px ${metrics.safeX}px`,
  };
}
