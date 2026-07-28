import { useEffect, useRef, useState } from "react";
import { MapPinned, RotateCcw, Volume2, VolumeX, X } from "lucide-react";
import { MapGamePromoVideo } from "../components/MapGamePromoVideo";

type MapGamePromoProps = {
  onDismiss?: () => void;
  onPlay?: () => void;
  playHref: string;
  reviewMode?: boolean;
};

const promoVideoSrc = "/videos/map-game-promo-vertical.mp4";
const promoPosterSrc = "/videos/map-game-promo-poster.png";

export function MapGamePromo({
  onDismiss,
  onPlay,
  playHref,
  reviewMode = false,
}: MapGamePromoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [muted, setMuted] = useState(true);
  const [ended, setEnded] = useState(false);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  async function replay() {
    const video = videoRef.current;
    if (!video) {
      return;
    }
    video.currentTime = 0;
    setEnded(false);
    try {
      await video.play();
    } catch {
      video.muted = true;
      setMuted(true);
      await video.play().catch(() => undefined);
    }
  }

  async function toggleSound() {
    const nextMuted = !muted;
    setMuted(nextMuted);
    const video = videoRef.current;
    if (!video) {
      return;
    }
    video.muted = nextMuted;
    if (!nextMuted && video.paused && !video.ended) {
      try {
        await video.play();
      } catch {
        video.muted = true;
        setMuted(true);
        await video.play().catch(() => undefined);
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] overflow-hidden bg-saints-black text-white"
      role={reviewMode ? undefined : "dialog"}
      aria-modal={reviewMode ? undefined : true}
      aria-label="New daily map game"
    >
      <div className="relative mx-auto flex h-dvh w-full max-w-[430px] flex-col overflow-hidden bg-black shadow-2xl ring-1 ring-white/10">
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <MapGamePromoVideo
            ref={videoRef}
            src={promoVideoSrc}
            poster={promoPosterSrc}
            className="h-full w-full object-contain"
            autoPlay
            muted={muted}
            onEnded={() => setEnded(true)}
            aria-label="Fulton's daily map game announcement"
          />

          <div className="absolute inset-x-0 top-0 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent px-3 pb-10 pt-[calc(0.75rem+env(safe-area-inset-top))]">
            <button
              type="button"
              onClick={() => void toggleSound()}
              className="saints-focus grid h-12 w-12 place-items-center rounded-full border border-white/25 bg-black/70 text-white shadow-lg backdrop-blur-sm"
              aria-label={muted ? "Turn sound on" : "Mute video"}
              title={muted ? "Turn sound on" : "Mute video"}
            >
              {muted ? (
                <VolumeX aria-hidden="true" className="h-6 w-6" strokeWidth={2.5} />
              ) : (
                <Volume2 aria-hidden="true" className="h-6 w-6" strokeWidth={2.5} />
              )}
            </button>

            {onDismiss ? (
              <button
                type="button"
                onClick={onDismiss}
                className="saints-focus grid h-12 w-12 place-items-center rounded-full border border-white/25 bg-black/70 text-white shadow-lg backdrop-blur-sm"
                aria-label="Close announcement"
                title="Close announcement"
              >
                <X aria-hidden="true" className="h-7 w-7" strokeWidth={2.5} />
              </button>
            ) : null}
          </div>

          {ended ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/80 to-transparent" />
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-2 border-t border-white/15 bg-saints-black px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
          <button
            type="button"
            onClick={() => void replay()}
            className="saints-focus grid h-14 w-14 shrink-0 place-items-center rounded-full border border-white/20 bg-white/10 text-white"
            aria-label="Replay announcement"
            title="Replay announcement"
          >
            <RotateCcw aria-hidden="true" className="h-6 w-6" strokeWidth={2.5} />
          </button>
          <a
            href={playHref}
            onClick={onPlay}
            className="saints-focus flex h-14 min-w-0 flex-1 items-center justify-center gap-2 rounded-md bg-saints-red px-3 text-center text-base font-black uppercase text-white shadow-lg no-underline transition-colors hover:bg-saints-redDark"
          >
            <MapPinned aria-hidden="true" className="h-6 w-6 shrink-0" strokeWidth={2.5} />
            <span>{reviewMode ? "Open live map" : "Play the map"}</span>
          </a>
        </div>
      </div>
    </div>
  );
}
