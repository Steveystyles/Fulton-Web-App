import { useCurrentFrame } from "remotion";
import { Explorer } from "../components/Explorer";
import { SceneBackground } from "../components/SceneBackground";
import { SpeechBubble } from "../components/SpeechBubble";
import { remotionTheme } from "../styles/theme";
import { fadeIn, slideUp } from "../utils/animation";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type ExplorerSceneProps = {
  metrics: LayoutMetrics;
};

export function ExplorerScene({ metrics }: ExplorerSceneProps) {
  const frame = useCurrentFrame();
  const explorerWidth = metrics.isVertical ? 470 : metrics.isSquare ? 390 : 430;

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "0.82fr 1.18fr" : "1fr",
          alignItems: "center",
          justifyItems: "center",
          gap: metrics.isLandscape ? 40 : 18,
        }}
      >
        <div
          style={{
            opacity: fadeIn(frame, 0, 16),
            translate: `${slideUp(frame, 0, 28, metrics.isLandscape ? -240 : 100)}px 0px`,
          }}
        >
          <Explorer pose="confident" frame={frame} width={explorerWidth} showMap />
        </div>
        <div
          style={{
            textAlign: metrics.isLandscape ? "left" : "center",
            maxWidth: 760,
          }}
        >
          <p
            style={{
              margin: "0 0 28px",
              color: remotionTheme.colors.red,
              fontFamily: remotionTheme.fontFamily,
              fontSize: metrics.label,
              fontWeight: 950,
              textTransform: "uppercase",
              opacity: fadeIn(frame, 9, 20),
            }}
          >
            Meet the overconfident explorer
          </p>
          <SpeechBubble frame={frame} delay={16} text="I've got this!" size="lg" tail="left" />
        </div>
      </div>
    </>
  );
}
