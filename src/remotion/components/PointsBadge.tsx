import { Easing, interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type PointsBadgeProps = {
  points: number;
  frame: number;
  tiny?: boolean;
  label?: string;
};

function scoreColors(points: number) {
  if (points === 10) {
    return {
      background: remotionTheme.colors.yellow,
      shadow: remotionTheme.shadow.red,
      color: remotionTheme.colors.ink,
    };
  }

  if (points === 7) {
    return {
      background: remotionTheme.colors.sky,
      shadow: remotionTheme.shadow.card,
      color: remotionTheme.colors.ink,
    };
  }

  if (points === 5) {
    return {
      background: remotionTheme.colors.mapLand,
      shadow: remotionTheme.shadow.card,
      color: remotionTheme.colors.ink,
    };
  }

  if (points === 2) {
    return {
      background: "#ffd8dc",
      shadow: "0 14px 30px rgba(169, 15, 24, 0.22)",
      color: remotionTheme.colors.redDark,
    };
  }

  return {
    background: remotionTheme.colors.cream,
    shadow: remotionTheme.shadow.card,
    color: remotionTheme.colors.ink,
  };
}

export function PointsBadge({ points, frame, tiny = false, label = "POINTS" }: PointsBadgeProps) {
  const scale = interpolate(frame, [0, 18], [tiny ? 0.96 : 0.985, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const colors = scoreColors(points);

  return (
    <div
      style={{
        display: "inline-flex",
        minWidth: tiny ? 118 : 178,
        alignItems: "center",
        justifyContent: "center",
        gap: tiny ? 8 : 12,
        border: `${tiny ? 4 : 6}px solid ${remotionTheme.colors.ink}`,
        borderRadius: remotionTheme.radius.pill,
        padding: tiny ? "9px 16px" : "16px 24px",
        background: colors.background,
        boxShadow: colors.shadow,
        color: colors.color,
        fontFamily: remotionTheme.fontFamily,
        fontWeight: 900,
        scale,
      }}
    >
      <span style={{ fontSize: tiny ? 30 : 52, lineHeight: 1 }}>{points}</span>
      <span style={{ fontSize: tiny ? 17 : 25, lineHeight: 0.92 }}>{label}</span>
    </div>
  );
}
