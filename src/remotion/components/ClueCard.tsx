import { interpolate, useVideoConfig } from "remotion";
import { remotionTheme } from "../styles/theme";
import { fitClueTextSize } from "../utils/validation";
import { popSpring } from "../utils/animation";

type ClueCardProps = {
  clueNumber: number;
  text: string;
  points: number;
  frame: number;
  delay?: number;
  answerReveal?: boolean;
  compact?: boolean;
};

export function ClueCard({
  clueNumber,
  text,
  points,
  frame,
  delay = 0,
  answerReveal = false,
  compact = false,
}: ClueCardProps) {
  const { fps, width } = useVideoConfig();
  const answerEntrance = popSpring(frame, fps, delay, 7);
  const cardScale = answerReveal
    ? 0.82 + answerEntrance * 0.18
    : interpolate(frame, [delay, delay + 14, delay + 24], [0.965, 1.012, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
  const opacity = interpolate(frame, [delay, delay + (answerReveal ? 8 : 18)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const baseSize = answerReveal ? (width > 1200 ? 108 : 70) : compact ? 31 : 43;
  const fontSize = answerReveal ? baseSize : fitClueTextSize(text, baseSize, compact ? 23 : 30);
  const cardBackground = answerReveal
    ? remotionTheme.colors.yellow
    : clueNumber % 2 === 0
      ? "#fff3d2"
      : "#f7efe2";
  const pointsBackground =
    points === 10
      ? remotionTheme.colors.yellow
      : points === 7
        ? remotionTheme.colors.sky
        : points === 5
          ? remotionTheme.colors.mapLand
          : "#ffd8dc";

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        overflow: "hidden",
        border: `${answerReveal ? 9 : 6}px solid ${remotionTheme.colors.ink}`,
        borderRadius: answerReveal ? remotionTheme.radius.lg : remotionTheme.radius.md,
        padding: answerReveal ? "44px 54px" : compact ? "20px 24px" : "30px 34px",
        background: cardBackground,
        boxShadow: answerReveal ? remotionTheme.shadow.heavy : remotionTheme.shadow.card,
        opacity,
        scale: cardScale,
        rotate: answerReveal ? `${interpolate(frame, [delay, delay + 10, delay + 22], [-5, 2, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })}deg` : "0deg",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 20,
          marginBottom: answerReveal ? 18 : 12,
        }}
      >
        <span
          style={{
            borderRadius: remotionTheme.radius.pill,
            padding: answerReveal ? "12px 22px" : "8px 16px",
            background: answerReveal ? remotionTheme.colors.ink : remotionTheme.colors.red,
            color: remotionTheme.colors.white,
            fontFamily: remotionTheme.fontFamily,
            fontSize: answerReveal ? 30 : 22,
            fontWeight: 900,
          }}
        >
          {answerReveal ? "ANSWER REVEAL" : `CLUE ${clueNumber}`}
        </span>
        <span
          style={{
            borderRadius: remotionTheme.radius.pill,
            padding: answerReveal ? "8px 16px" : "7px 13px",
            background: pointsBackground,
            color: points === 2 ? remotionTheme.colors.redDark : remotionTheme.colors.ink,
            boxShadow: "inset 0 0 0 3px rgba(17, 17, 20, 0.12)",
            fontSize: answerReveal ? 22 : 18,
            fontWeight: 900,
          }}
        >
          {points} POINTS
        </span>
      </div>
      <p
        style={{
          margin: 0,
          color: remotionTheme.colors.ink,
          fontFamily: remotionTheme.fontFamily,
          fontSize,
          fontWeight: answerReveal ? 900 : 850,
          lineHeight: answerReveal ? 0.96 : 1.12,
          textTransform: answerReveal ? "uppercase" : "none",
          textWrap: "balance",
        }}
      >
        {text}
      </p>
    </div>
  );
}
