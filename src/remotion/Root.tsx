import { Composition } from "remotion";
import { MapGamePromo } from "./MapGamePromo";
import { defaultGamePromoData } from "./data/defaultGamePromoData";
import { defaultAudioSettings } from "./types";
import { DURATION_IN_FRAMES, FPS } from "./utils/timing";

export const compositionDefinitions = [
  {
    id: "MapGamePromo",
    width: 1920,
    height: 1080,
    format: "landscape",
  },
  {
    id: "MapGamePromoSquare",
    width: 1080,
    height: 1080,
    format: "square",
  },
  {
    id: "MapGamePromoVertical",
    width: 1080,
    height: 1920,
    format: "vertical",
  },
] as const;

export const RemotionRoot = () => {
  return (
    <>
      {compositionDefinitions.map((composition) => (
        <Composition
          key={composition.id}
          id={composition.id}
          component={MapGamePromo}
          durationInFrames={DURATION_IN_FRAMES}
          fps={FPS}
          width={composition.width}
          height={composition.height}
          defaultProps={{
            data: defaultGamePromoData,
            format: composition.format,
            audioSettings: defaultAudioSettings,
          }}
        />
      ))}
    </>
  );
};
