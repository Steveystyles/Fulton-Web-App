import { interpolate } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { remotionTheme } from "../styles/theme";

type ScoreboardProps = {
  data: GamePromoData;
  frame: number;
};

export function Scoreboard({ data, frame }: ScoreboardProps) {
  const rows = data.clues.map((clue, index) => ({
    label: `${index + 1} ${index === 0 ? "clue" : "clues"}`,
    points: clue.points,
  }));

  return (
    <div
      style={{
        width: "100%",
        border: `7px solid ${remotionTheme.colors.ink}`,
        borderRadius: remotionTheme.radius.lg,
        overflow: "hidden",
        background: remotionTheme.colors.paper,
        boxShadow: remotionTheme.shadow.heavy,
        fontFamily: remotionTheme.fontFamily,
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 0.68fr",
          background: remotionTheme.colors.ink,
          color: remotionTheme.colors.white,
          fontSize: 34,
          fontWeight: 900,
          padding: "22px 34px",
        }}
      >
        <span>CLUES NEEDED</span>
        <span style={{ textAlign: "right" }}>POINTS</span>
      </div>
      {rows.map((row, index) => {
        const rowFrame = frame - index * 10;
        const slide = interpolate(rowFrame, [8, 24], [70, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const opacity = interpolate(rowFrame, [8, 20], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const isBest = row.points === 10;
        const isSad = row.points === 2;

        return (
          <div
            key={row.label}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 0.68fr",
              alignItems: "center",
              minHeight: 98,
              borderTop: `4px solid ${remotionTheme.colors.line}`,
              padding: "14px 34px",
              background: index % 2 === 0 ? remotionTheme.colors.cream : "#efece3",
              opacity,
              translate: `${slide}px 0px`,
            }}
          >
            <span
              style={{
                color: remotionTheme.colors.ink,
                fontSize: 42,
                fontWeight: 900,
                textTransform: "uppercase",
              }}
            >
              {row.label}
            </span>
            <span
              style={{
                color: isSad ? remotionTheme.colors.redDark : remotionTheme.colors.ink,
                fontSize: isBest ? 82 : isSad ? 43 : 64,
                fontWeight: 950,
                lineHeight: 1,
                textAlign: "right",
              }}
            >
              {row.points}
            </span>
          </div>
        );
      })}
    </div>
  );
}
