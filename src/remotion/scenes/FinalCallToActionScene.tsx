import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { CallToAction } from "../components/CallToAction";
import { Confetti } from "../components/Confetti";
import { Explorer } from "../components/Explorer";
import { Globe } from "../components/Globe";
import { SceneBackground } from "../components/SceneBackground";
import { remotionTheme } from "../styles/theme";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type FinalCallToActionSceneProps = {
  data: GamePromoData;
  metrics: LayoutMetrics;
};

function PaperPlane({ frame }: { frame: number }) {
  return (
    <svg viewBox="0 0 220 110" width="220" height="110" aria-hidden="true" style={{ overflow: "visible" }}>
      <g
        transform={`translate(${interpolate(frame, [48, 78], [0, 360], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })} ${interpolate(frame, [48, 78], [0, -92], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })}) rotate(-12)`}
        opacity={interpolate(frame, [45, 54, 82], [0, 1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })}
      >
        <path d="M12 53L204 8l-57 91-39-44-49 35Z" fill={remotionTheme.colors.white} stroke={remotionTheme.colors.ink} strokeWidth="8" strokeLinejoin="round" />
        <path d="M108 55l96-47-57 91Z" fill={remotionTheme.colors.mist} stroke={remotionTheme.colors.ink} strokeWidth="6" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

export function FinalCallToActionScene({ data, metrics }: FinalCallToActionSceneProps) {
  const frame = useCurrentFrame();
  const compactFinal = !metrics.isLandscape;
  const explorerExitEnd = compactFinal ? 66 : 80;
  const explorerExit = interpolate(frame, [52, explorerExitEnd], [0, metrics.isVertical ? 820 : metrics.isSquare ? 620 : 460], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} variant="dark" />
      <Confetti frame={frame} start={8} originX={50} originY={30} count={34} seed={133} />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "0.86fr 1.14fr" : "1fr",
          alignItems: "center",
          justifyItems: "center",
          gap: metrics.isLandscape ? 44 : 22,
        }}
      >
        <div
          style={{
            position: "relative",
            display: "grid",
            justifyItems: "center",
          }}
        >
          <Globe frame={frame + 30} size={metrics.isVertical ? 500 : metrics.isSquare ? 390 : 480} showPin />
          <div
            style={{
              position: "absolute",
              top: metrics.isVertical ? 150 : 136,
              display: "grid",
              placeItems: "center",
              width: metrics.isVertical ? 150 : 138,
              height: metrics.isVertical ? 150 : 138,
              border: `6px solid ${remotionTheme.colors.ink}`,
              borderRadius: remotionTheme.radius.pill,
              background: remotionTheme.colors.white,
              boxShadow: remotionTheme.shadow.card,
            }}
          >
            <Img src={staticFile("favicon.svg")} style={{ width: "82%", height: "82%", objectFit: "contain" }} />
          </div>
        </div>
        <div style={{ width: "100%", textAlign: "center" }}>
          <h2
            style={{
              margin: 0,
              color: remotionTheme.colors.white,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.headline * (metrics.isLandscape ? 0.86 : 0.72),
              fontWeight: 950,
              lineHeight: 0.9,
              textTransform: "uppercase",
              textShadow: "0 6px 0 rgba(5, 5, 5, 0.3)",
            }}
          >
            Can you score 10?
          </h2>
          <p
            style={{
              margin: "22px 0 30px",
              color: "rgba(255, 255, 255, 0.84)",
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.subhead * 0.72,
              fontWeight: 850,
            }}
          >
            Find it before the final clue!
          </p>
          <CallToAction
            frame={frame}
            label={data.callToAction}
            secondary={data.secondaryCallToAction}
            url={data.websiteUrl}
          />
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: metrics.isLandscape ? metrics.safeX + 30 : metrics.width * 0.12,
          bottom: metrics.isVertical ? metrics.safeY + 110 : metrics.safeY,
          opacity: interpolate(frame, [0, 14, compactFinal ? 58 : 72, compactFinal ? 68 : 82], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: `${explorerExit}px 0px`,
        }}
      >
        <Explorer pose="celebrating" frame={frame} width={metrics.isVertical ? 270 : 310} />
        <div style={{ position: "absolute", left: 120, bottom: 12 }}>
          <PaperPlane frame={frame} />
        </div>
      </div>
    </>
  );
}
