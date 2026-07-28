import { interpolate, useCurrentFrame } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { Confetti } from "../components/Confetti";
import { Explorer } from "../components/Explorer";
import { GameMap, mapCoordinates } from "../components/GameMap";
import { LockedPin } from "../components/LockedPin";
import { MapPin } from "../components/MapPin";
import { SceneBackground } from "../components/SceneBackground";
import { SpeechBubble } from "../components/SpeechBubble";
import { remotionTheme } from "../styles/theme";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type MapGuessSceneProps = {
  data: GamePromoData;
  metrics: LayoutMetrics;
};

function mapComment(frame: number) {
  if (frame < 40) {
    return null;
  }

  if (frame < 76) {
    return "South America? Bold start.";
  }

  if (frame < 110) {
    return "Greenland felt confidently north.";
  }

  if (frame < 144) {
    return "Ocean guess. Let's call it strategy.";
  }

  return "Locked! Obviously my plan all along.";
}

export function MapGuessScene({ data, metrics }: MapGuessSceneProps) {
  const frame = useCurrentFrame();
  const correctStart = 132;
  const locked = frame >= correctStart + 28;
  const explorerPose = locked ? "celebrating" : frame > 96 ? "shocked" : "thinking";
  const mapHeight = metrics.isVertical ? 860 : metrics.isSquare ? 610 : 760;
  const comment = mapComment(frame);

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} variant="map" />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "0.76fr 1.24fr" : "1fr",
          alignItems: "center",
          justifyItems: "center",
          gap: metrics.isLandscape ? 34 : 24,
        }}
      >
        <div
          style={{
            display: "grid",
            justifyItems: "center",
            gap: 14,
            order: metrics.isLandscape ? 0 : 2,
          }}
        >
          <Explorer pose={explorerPose} frame={frame} width={metrics.isVertical ? 350 : 330} />
          {comment ? <SpeechBubble frame={frame} delay={40} text={comment} size="sm" tail="top-left" /> : null}
        </div>
        <div style={{ width: "100%" }}>
          <h2
            style={{
              margin: "0 0 22px",
              color: remotionTheme.colors.ink,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.isLandscape ? 72 : 55,
              fontWeight: 950,
              lineHeight: 0.95,
              textAlign: metrics.isLandscape ? "left" : "center",
              textTransform: "uppercase",
            }}
          >
            Now find it on the map
          </h2>
          <div
            style={{
              position: "relative",
              width: "100%",
              height: mapHeight,
              borderRadius: remotionTheme.radius.lg,
              boxShadow: remotionTheme.shadow.heavy,
              overflow: "hidden",
            }}
          >
            <GameMap showLabels={!metrics.isVertical || frame > 94}>
              <MapPin frame={frame} start={28} {...mapCoordinates.southAmerica} />
              <MapPin frame={frame} start={64} {...mapCoordinates.greenland} />
              <MapPin frame={frame} start={96} {...mapCoordinates.ocean} ocean />
              <MapPin frame={frame} start={correctStart} {...mapCoordinates.kathmandu} correct />
              <LockedPin frame={frame} start={correctStart + 20} {...mapCoordinates.kathmandu} />
            </GameMap>
            {locked ? (
              <div
                style={{
                  position: "absolute",
                  right: 44,
                  bottom: 44,
                  border: `6px solid ${remotionTheme.colors.ink}`,
                  borderRadius: remotionTheme.radius.pill,
                  padding: "18px 30px",
                  background: remotionTheme.colors.green,
                  color: remotionTheme.colors.white,
                  fontFamily: remotionTheme.fontFamily,
                  fontSize: metrics.isVertical ? 34 : 42,
                  fontWeight: 950,
                  opacity: interpolate(frame, [correctStart + 24, correctStart + 34], [0, 1], {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  }),
                }}
              >
                GUESS LOCKED
              </div>
            ) : null}
            <Confetti frame={frame} start={correctStart + 36} originX={72} originY={48} seed={87} />
          </div>
          <p
            style={{
              margin: "18px 0 0",
              color: remotionTheme.colors.ink,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.label,
              fontWeight: 850,
              textAlign: metrics.isLandscape ? "left" : "center",
            }}
          >
            The answer: {data.locationName}, {data.countryName}. Drop a pin when you are ready.
          </p>
        </div>
      </div>
    </>
  );
}
