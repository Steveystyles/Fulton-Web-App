import { interpolate, useCurrentFrame } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { Explorer } from "../components/Explorer";
import { SceneBackground } from "../components/SceneBackground";
import { Scoreboard } from "../components/Scoreboard";
import { remotionTheme } from "../styles/theme";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type ScoreExplanationSceneProps = {
  data: GamePromoData;
  metrics: LayoutMetrics;
};

export function ScoreExplanationScene({ data, metrics }: ScoreExplanationSceneProps) {
  const frame = useCurrentFrame();
  const stickerX = interpolate(frame, [58, 80, 95], [220, 0, 80], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stampOpacity = interpolate(frame, [84, 94], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "1.1fr 0.9fr" : "1fr",
          alignItems: "center",
          justifyItems: "center",
          gap: metrics.isLandscape ? 44 : 26,
        }}
      >
        <div style={{ width: "100%", position: "relative" }}>
          <h2
            style={{
              margin: "0 0 24px",
              color: remotionTheme.colors.ink,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.isLandscape ? 74 : 56,
              fontWeight: 950,
              lineHeight: 0.95,
              textTransform: "uppercase",
              textAlign: metrics.isLandscape ? "left" : "center",
            }}
          >
            Earlier answers score bigger
          </h2>
          <Scoreboard data={data} frame={frame} />
          {frame > 56 ? (
            <div
              style={{
                position: "absolute",
                right: metrics.isLandscape ? 36 : 28,
                bottom: metrics.isLandscape ? 28 : 24,
                border: `6px solid ${remotionTheme.colors.ink}`,
                borderRadius: remotionTheme.radius.md,
                padding: "4px 18px",
                background: remotionTheme.colors.yellow,
                color: remotionTheme.colors.ink,
                fontFamily: remotionTheme.fontFamily,
                fontSize: 66,
                fontWeight: 950,
                opacity: interpolate(frame, [56, 66, 100], [0, 1, 0], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                }),
                translate: `${stickerX}px 0px`,
                rotate: `${interpolate(frame, [58, 80, 94], [-14, 4, -18], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                })}deg`,
              }}
            >
              10
            </div>
          ) : null}
          <div
            style={{
              position: "absolute",
              right: metrics.isLandscape ? 138 : 92,
              bottom: metrics.isLandscape ? 108 : 98,
              border: `8px solid ${remotionTheme.colors.red}`,
              borderRadius: remotionTheme.radius.md,
              padding: "10px 22px",
              color: remotionTheme.colors.red,
              background: "rgba(255, 255, 255, 0.88)",
              fontFamily: remotionTheme.fontFamily,
              fontSize: 45,
              fontWeight: 950,
              opacity: stampOpacity,
              rotate: "-12deg",
            }}
          >
            NICE TRY!
          </div>
        </div>
        <div
          style={{
            display: "grid",
            justifyItems: "center",
            alignContent: "center",
            translate: `${interpolate(frame, [34, 74], [metrics.isLandscape ? 170 : 90, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}px 0px`,
          }}
        >
          <Explorer pose={frame > 86 ? "confident" : "sneaking"} frame={frame} width={metrics.isVertical ? 360 : 390} />
          <p
            style={{
              margin: "-18px 0 0",
              color: remotionTheme.colors.ink,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.label,
              fontWeight: 900,
              opacity: interpolate(frame, [92, 112], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            Just checking the rules.
          </p>
        </div>
      </div>
    </>
  );
}
