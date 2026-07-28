import type { CSSProperties } from "react";
import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type TravelStickerProps = {
  frame: number;
  delay: number;
  label: string;
  tone: "red" | "yellow" | "black" | "green";
  style: CSSProperties;
};

const toneColor = {
  red: remotionTheme.colors.red,
  yellow: remotionTheme.colors.yellow,
  black: remotionTheme.colors.ink,
  green: remotionTheme.colors.green,
};

export function TravelSticker({ frame, delay, label, tone, style }: TravelStickerProps) {
  const progress = interpolate(frame, [delay, delay + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        minWidth: 130,
        border: `5px solid ${remotionTheme.colors.ink}`,
        borderRadius: remotionTheme.radius.md,
        padding: "14px 18px",
        background: remotionTheme.colors.white,
        boxShadow: remotionTheme.shadow.card,
        color: toneColor[tone],
        fontFamily: remotionTheme.fontFamily,
        fontSize: 24,
        fontWeight: 900,
        letterSpacing: 0,
        textAlign: "center",
        opacity: progress,
        scale: progress,
        ...style,
      }}
    >
      {label}
    </div>
  );
}
