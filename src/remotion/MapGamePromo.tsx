import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { Soundtrack } from "./components/Soundtrack";
import { IntroScene } from "./scenes/IntroScene";
import { ExplorerScene } from "./scenes/ExplorerScene";
import { ClueSequenceScene } from "./scenes/ClueSequenceScene";
import { MapGuessScene } from "./scenes/MapGuessScene";
import { ScoreExplanationScene } from "./scenes/ScoreExplanationScene";
import { FinalCallToActionScene } from "./scenes/FinalCallToActionScene";
import { remotionTheme } from "./styles/theme";
import type { MapGamePromoProps } from "./types";
import { getLayoutMetrics } from "./utils/layout";
import { sceneTimings } from "./utils/timing";
import { validateGamePromoData, validateSceneTimings } from "./utils/validation";

export function MapGamePromo({ data, format, audioSettings }: MapGamePromoProps) {
  validateGamePromoData(data);
  validateSceneTimings();

  const { width, height } = useVideoConfig();
  const metrics = getLayoutMetrics(width, height, format);

  return (
    <AbsoluteFill
      style={{
        width,
        height,
        overflow: "hidden",
        background: remotionTheme.colors.black,
        color: remotionTheme.colors.ink,
        fontFamily: remotionTheme.fontFamily,
      }}
    >
      <Soundtrack audioSettings={audioSettings} />
      <Sequence from={sceneTimings.intro.start} durationInFrames={sceneTimings.intro.duration}>
        <IntroScene data={data} metrics={metrics} />
      </Sequence>
      <Sequence from={sceneTimings.explorer.start} durationInFrames={sceneTimings.explorer.duration}>
        <ExplorerScene metrics={metrics} />
      </Sequence>
      <Sequence from={sceneTimings.clues.start} durationInFrames={sceneTimings.clues.duration}>
        <ClueSequenceScene data={data} metrics={metrics} />
      </Sequence>
      <Sequence from={sceneTimings.mapGuess.start} durationInFrames={sceneTimings.mapGuess.duration}>
        <MapGuessScene data={data} metrics={metrics} />
      </Sequence>
      <Sequence from={sceneTimings.scoring.start} durationInFrames={sceneTimings.scoring.duration}>
        <ScoreExplanationScene data={data} metrics={metrics} />
      </Sequence>
      <Sequence from={sceneTimings.finalCta.start} durationInFrames={sceneTimings.finalCta.duration}>
        <FinalCallToActionScene data={data} metrics={metrics} />
      </Sequence>
    </AbsoluteFill>
  );
}
