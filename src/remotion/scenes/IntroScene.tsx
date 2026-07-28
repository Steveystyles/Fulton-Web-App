import { useCurrentFrame, useVideoConfig } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { Globe } from "../components/Globe";
import { SceneBackground } from "../components/SceneBackground";
import { TravelSticker } from "../components/TravelSticker";
import { remotionTheme } from "../styles/theme";
import { fadeIn, impactShake, popSpring, slideUp } from "../utils/animation";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type IntroSceneProps = {
  data: GamePromoData;
  metrics: LayoutMetrics;
};

export function IntroScene({ data, metrics }: IntroSceneProps) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const shake = impactShake(frame, 34, metrics.isVertical ? 8 : 12);
  const globeSize = metrics.isLandscape ? 520 : metrics.isVertical ? 560 : 420;
  const globeScale = 0.62 + popSpring(frame, fps, 0, 9) * 0.38;

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} />
      <TravelSticker frame={frame} delay={38} label="PASSPORT" tone="red" style={{ left: metrics.safeX, top: metrics.safeY + 10, rotate: "-9deg" }} />
      <TravelSticker frame={frame} delay={42} label="AIRMILES?" tone="black" style={{ right: metrics.safeX, top: metrics.safeY + 30, rotate: "8deg" }} />
      <TravelSticker frame={frame} delay={48} label="+10 PTS" tone="yellow" style={{ left: metrics.isVertical ? metrics.safeX + 80 : metrics.width * 0.13, bottom: metrics.safeY + 35, rotate: "6deg" }} />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "0.95fr 1.05fr" : "1fr",
          alignItems: "center",
          justifyItems: "center",
          gap: metrics.isLandscape ? 48 : 30,
          translate: `${shake}px ${shake * 0.32}px`,
        }}
      >
        <Globe
          frame={frame}
          size={globeSize}
          showPin
          wobble={impactShake(frame, 34, 7)}
          style={{
            scale: globeScale,
          }}
        />
        <div
          style={{
            maxWidth: metrics.isLandscape ? 830 : metrics.isVertical ? 840 : 820,
            textAlign: metrics.isLandscape ? "left" : "center",
            opacity: fadeIn(frame, 24, 46),
            translate: `0px ${slideUp(frame, 24, 48, 54)}px`,
          }}
        >
          <div
            style={{
              display: "inline-flex",
              borderRadius: remotionTheme.radius.pill,
              padding: "14px 24px",
              background: remotionTheme.colors.red,
              color: remotionTheme.colors.white,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.label,
              fontWeight: 950,
              textTransform: "uppercase",
              boxShadow: remotionTheme.shadow.red,
            }}
          >
            NEW DAILY GAME!
          </div>
          <h1
            style={{
              margin: "28px 0 0",
              color: remotionTheme.colors.ink,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.headline,
              fontWeight: 950,
              lineHeight: 0.9,
              textTransform: "uppercase",
              textWrap: "balance",
            }}
          >
            {data.gameTitle}
          </h1>
          <p
            style={{
              margin: "26px 0 0",
              color: remotionTheme.colors.redDark,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.subhead,
              fontWeight: 900,
              lineHeight: 1,
            }}
          >
            Four clues. One map. Zero excuses.
          </p>
        </div>
      </div>
    </>
  );
}
