import { interpolate, useCurrentFrame } from "remotion";
import type { GamePromoData } from "../data/defaultGamePromoData";
import { ClueCard } from "../components/ClueCard";
import { Explorer, type ExplorerPose } from "../components/Explorer";
import { PointsBadge } from "../components/PointsBadge";
import { SceneBackground } from "../components/SceneBackground";
import { SpeechBubble } from "../components/SpeechBubble";
import { remotionTheme } from "../styles/theme";
import { impactShake } from "../utils/animation";
import type { LayoutMetrics } from "../utils/layout";
import { safeAreaStyle } from "../utils/layout";

type ClueSequenceSceneProps = {
  data: GamePromoData;
  metrics: LayoutMetrics;
};

const clueStarts = [0, 66, 132, 198] as const;

function activeClue(frame: number) {
  if (frame >= clueStarts[3]) {
    return 3;
  }
  if (frame >= clueStarts[2]) {
    return 2;
  }
  if (frame >= clueStarts[1]) {
    return 1;
  }
  return 0;
}

function explorerPose(frame: number, active: number): ExplorerPose {
  if (active === 3) {
    return frame > 226 ? "facepalm" : "shocked";
  }

  if (active === 2) {
    return "excited";
  }

  if (active === 1 || frame > 42) {
    return "thinking";
  }

  return "confident";
}

export function ClueSequenceScene({ data, metrics }: ClueSequenceSceneProps) {
  const frame = useCurrentFrame();
  const active = activeClue(frame);
  const currentClue = data.clues[active];
  const shake = impactShake(frame, clueStarts[3] + 9, metrics.isVertical ? 9 : 13);
  const answerMode = active === 3;
  const sideBySide = metrics.isLandscape || metrics.isSquare;
  const explorerWidth = metrics.isVertical ? 390 : metrics.isSquare ? 270 : 360;
  const cardAreaHeight = metrics.isVertical ? 760 : metrics.isSquare ? 620 : 650;

  return (
    <>
      <SceneBackground frame={frame} metrics={metrics} />
      <div
        style={{
          ...safeAreaStyle(metrics),
          display: "grid",
          gridTemplateColumns: metrics.isLandscape ? "0.72fr 1.28fr" : metrics.isSquare ? "0.55fr 1.45fr" : "1fr",
          gridTemplateRows: sideBySide ? "1fr" : "auto 1fr",
          alignItems: "center",
          gap: sideBySide ? 34 : 22,
          translate: `${shake}px ${shake * 0.25}px`,
        }}
      >
        <div
          style={{
            display: "grid",
            justifyItems: "center",
            alignContent: "center",
            gap: 18,
            order: sideBySide ? 0 : 2,
          }}
        >
          <Explorer
            pose={explorerPose(frame, active)}
            frame={frame}
            width={explorerWidth}
            showMap={active < 2}
          />
          {active === 2 ? <SpeechBubble frame={frame} delay={8} text="I KNOW IT!" size="md" tail="top-left" /> : null}
          {answerMode ? <SpeechBubble frame={frame} delay={32} text="Oh... right." size="sm" tail="top-left" /> : null}
          {answerMode ? (
            <div
              style={{
                width: 120,
                height: 72,
                borderRadius: "50% 50% 48% 48%",
                background: "#8ca0aa",
                opacity: interpolate(frame, [222, 246, 268], [0, 0.72, 0], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                }),
              }}
            />
          ) : null}
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 22,
              marginBottom: 24,
            }}
          >
            <div>
              <p
                style={{
                  margin: 0,
                  color: remotionTheme.colors.red,
                  fontFamily: remotionTheme.fontFamily,
                  fontSize: metrics.label,
                  fontWeight: 950,
                  textTransform: "uppercase",
                }}
              >
                Decide when you know it
              </p>
              <h2
                style={{
                  margin: "8px 0 0",
                  color: remotionTheme.colors.ink,
                  fontFamily: remotionTheme.fontFamily,
                  fontSize: metrics.isLandscape ? 62 : 48,
                  fontWeight: 950,
                  lineHeight: 0.96,
                }}
              >
                Clues get easier. Points get sadder.
              </h2>
            </div>
            <PointsBadge points={currentClue.points} frame={frame - clueStarts[active]} tiny={answerMode} />
          </div>
          <div
            style={{
              position: "relative",
              minHeight: cardAreaHeight,
            }}
          >
            {!answerMode ? (
              <div
                style={{
                  display: "grid",
                  gap: metrics.isVertical ? 18 : 22,
                }}
              >
                {data.clues.slice(0, active + 1).map((clue, index) => (
                  <div
                    key={clue.text}
                    style={{
                      opacity: index < active ? 0.78 : 1,
                      scale: index < active ? 0.93 : 1,
                    }}
                  >
                    <ClueCard
                      clueNumber={index + 1}
                      text={clue.text}
                      points={clue.points}
                      frame={frame}
                      delay={clueStarts[index]}
                      compact={index < active || metrics.isVertical}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <>
                {data.clues.slice(0, 3).map((clue, index) => (
                  <div
                    key={clue.text}
                    style={{
                      position: "absolute",
                      left: metrics.isSquare ? `${index * 8}%` : `${index * 12}%`,
                      top: 8 + index * 82,
                      width: metrics.isVertical ? "84%" : metrics.isSquare ? "68%" : "55%",
                      opacity: 0.44,
                      translate: `${interpolate(frame, [198, 218], [0, -80 + index * 35], {
                        extrapolateLeft: "clamp",
                        extrapolateRight: "clamp",
                      })}px 0px`,
                      rotate: `${[-11, 7, -5][index]}deg`,
                    }}
                  >
                    <ClueCard
                      clueNumber={index + 1}
                      text={clue.text}
                      points={clue.points}
                      frame={frame}
                      delay={0}
                      compact
                    />
                  </div>
                ))}
                <div
                  style={{
                    position: "absolute",
                    inset: metrics.isVertical ? "140px 0 auto" : "100px 0 auto",
                    margin: "0 auto",
                    width: metrics.isLandscape ? "92%" : "100%",
                  }}
                >
                  <ClueCard
                    clueNumber={4}
                    text={data.locationName}
                    points={data.clues[3].points}
                    frame={frame}
                    delay={clueStarts[3]}
                    answerReveal
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
