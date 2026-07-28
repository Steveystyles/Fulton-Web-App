import { useEffect, useRef, useState } from "react";

export type MapGamePromoVideoProps = {
  src: string;
  poster?: string;
  className?: string;
  autoPlay?: boolean;
  muted?: boolean;
  loop?: boolean;
};

export function MapGamePromoVideo({
  src,
  poster,
  className = "",
  autoPlay = true,
  muted = true,
  loop = true,
}: MapGamePromoVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(query.matches);

    const onChange = () => setPrefersReducedMotion(query.matches);
    query.addEventListener("change", onChange);

    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || prefersReducedMotion || !autoPlay) {
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          void video.play().catch(() => undefined);
        } else {
          video.pause();
        }
      },
      { threshold: 0.25 },
    );

    observer.observe(video);

    return () => observer.disconnect();
  }, [autoPlay, prefersReducedMotion]);

  if (prefersReducedMotion && poster) {
    return (
      <img
        src={poster}
        alt="Guess the Location promotional preview"
        className={className}
        loading="lazy"
        decoding="async"
      />
    );
  }

  return (
    <video
      ref={videoRef}
      className={className}
      src={src}
      poster={poster}
      autoPlay={!prefersReducedMotion && autoPlay}
      muted={muted}
      loop={loop}
      playsInline
      controls={!autoPlay || prefersReducedMotion}
      preload="none"
    />
  );
}
