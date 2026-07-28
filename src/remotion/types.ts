import type { GamePromoData } from "./data/defaultGamePromoData";
import type { PromoFormat } from "./utils/layout";

export type AudioSettings = {
  enabled: boolean;
  musicVolume: number;
  effectsVolume: number;
};

export type MapGamePromoProps = {
  data: GamePromoData;
  format: PromoFormat;
  audioSettings: AudioSettings;
};

export const defaultAudioSettings: AudioSettings = {
  enabled: true,
  musicVolume: 0.16,
  effectsVolume: 0.42,
};
