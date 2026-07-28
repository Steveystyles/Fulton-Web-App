import {
  forwardRef,
  useEffect,
  useState,
  type VideoHTMLAttributes,
} from "react";

type MapGamePromoVideoProps = Omit<
  VideoHTMLAttributes<HTMLVideoElement>,
  "children" | "poster" | "src"
> & {
  poster: string;
  src: string;
};

export const MapGamePromoVideo = forwardRef<
  HTMLVideoElement,
  MapGamePromoVideoProps
>(function MapGamePromoVideo(
  { className = "", onError, poster, src, ...videoProps },
  forwardedRef,
) {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = () => setPrefersReducedMotion(query.matches);

    updatePreference();
    query.addEventListener("change", updatePreference);
    return () => query.removeEventListener("change", updatePreference);
  }, []);

  if (prefersReducedMotion || videoFailed) {
    return (
      <img
        src={poster}
        alt="Fulton's new daily map game"
        className={className}
        decoding="async"
      />
    );
  }

  return (
    <video
      {...videoProps}
      ref={forwardedRef}
      className={className}
      src={src}
      poster={poster}
      playsInline
      preload="auto"
      onError={(event) => {
        setVideoFailed(true);
        onError?.(event);
      }}
    />
  );
});
