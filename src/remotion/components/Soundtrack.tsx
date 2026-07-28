import { Audio, Sequence, getStaticFiles, staticFile } from "remotion";
import type { AudioSettings } from "../types";

type SoundtrackProps = {
  audioSettings: AudioSettings;
};

const audioFiles = {
  music: "audio/map-game-music-loop.wav",
  whoosh: "audio/map-game-whoosh.wav",
  impact: "audio/map-game-impact.wav",
  pop: "audio/map-game-pop.wav",
  crash: "audio/map-game-answer-crash.wav",
  sad: "audio/map-game-sad-trombone.wav",
  boing: "audio/map-game-boing.wav",
  splash: "audio/map-game-splash.wav",
  click: "audio/map-game-lock-click.wav",
  success: "audio/map-game-success-chime.wav",
  confetti: "audio/map-game-confetti.wav",
} as const;

function clampVolume(value: number) {
  return Math.min(0.9, Math.max(0, value));
}

export function Soundtrack({ audioSettings }: SoundtrackProps) {
  if (!audioSettings.enabled) {
    return null;
  }

  const files = getStaticFiles();
  const hasFile = (name: string) => files.some((file) => file.name === name);
  const musicVolume = clampVolume(audioSettings.musicVolume);
  const effectsVolume = clampVolume(audioSettings.effectsVolume);
  const effect = (name: keyof typeof audioFiles, from: number, multiplier = 1) => {
    const file = audioFiles[name];
    if (!hasFile(file)) {
      return null;
    }

    return (
      <Sequence key={`${name}-${from}`} from={from} layout="none">
        <Audio src={staticFile(file)} volume={clampVolume(effectsVolume * multiplier)} />
      </Sequence>
    );
  };

  return (
    <>
      {hasFile(audioFiles.music) ? (
        <Audio src={staticFile(audioFiles.music)} volume={musicVolume} loop />
      ) : null}
      {effect("whoosh", 0, 0.75)}
      {effect("impact", 33, 0.88)}
      {[158, 224, 289].map((from) => effect("pop", from, 0.62))}
      {effect("crash", 346, 0.82)}
      {effect("sad", 372, 0.58)}
      {[454, 489].map((from) => effect("boing", from, 0.7))}
      {effect("splash", 524, 0.78)}
      {effect("click", 560, 0.74)}
      {effect("success", 568, 0.72)}
      {effect("confetti", 574, 0.68)}
      {effect("pop", 625, 0.55)}
      {effect("pop", 636, 0.55)}
      {effect("pop", 647, 0.55)}
      {effect("pop", 658, 0.55)}
      {effect("boing", 690, 0.55)}
      {effect("success", 742, 0.62)}
    </>
  );
}
