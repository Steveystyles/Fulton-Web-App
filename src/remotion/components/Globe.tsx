import type { CSSProperties } from "react";
import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type GlobeProps = {
  frame: number;
  size: number;
  showPin?: boolean;
  wobble?: number;
  style?: CSSProperties;
};

export function Globe({ frame, size, showPin = false, wobble = 0, style }: GlobeProps) {
  const spin = (frame * 5) % 360;
  const pinDrop = interpolate(frame, [18, 34], [-240, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pinScale = interpolate(frame, [32, 38, 48], [1, 0.78, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: size,
        height: size,
        rotate: `${wobble}deg`,
        ...style,
      }}
    >
      <svg viewBox="0 0 420 420" width="100%" height="100%" aria-hidden="true" style={{ overflow: "visible" }}>
        <defs>
          <clipPath id="map-promo-globe-clip">
            <circle cx="210" cy="210" r="165" />
          </clipPath>
          <radialGradient id="map-promo-globe-glow" cx="32%" cy="22%" r="78%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.72" />
            <stop offset="38%" stopColor={remotionTheme.colors.sky} />
            <stop offset="100%" stopColor={remotionTheme.colors.ocean} />
          </radialGradient>
        </defs>
        <circle cx="210" cy="210" r="184" fill={remotionTheme.colors.white} opacity="0.75" />
        <circle cx="210" cy="210" r="166" fill="url(#map-promo-globe-glow)" stroke={remotionTheme.colors.ink} strokeWidth="10" />
        <g clipPath="url(#map-promo-globe-clip)">
          <g transform={`translate(${Math.sin(spin * (Math.PI / 180)) * 50} 0)`}>
            <path
              d="M42 154c34-44 95-48 120-22 18 19 3 42 27 61 28 22 72 0 94 28 20 25-1 72-38 83-43 13-91-21-116-57-18-27-24-58-53-61-16-2-29 6-43 0-20-9-18-24 9-32Z"
              fill={remotionTheme.colors.mapLand}
              stroke={remotionTheme.colors.mapLandDark}
              strokeWidth="5"
            />
            <path
              d="M275 112c49-19 105 9 115 50 9 36-18 68-49 72-23 2-29-12-54-8-24 4-38 20-55 11-18-10-19-39-7-63 11-22 28-53 50-62Z"
              fill={remotionTheme.colors.mapLand}
              stroke={remotionTheme.colors.mapLandDark}
              strokeWidth="5"
            />
            <path
              d="M214 284c29-13 72-5 91 21 18 24 8 56-18 72-32 20-85 4-101-30-13-26 2-51 28-63Z"
              fill={remotionTheme.colors.mapLand}
              stroke={remotionTheme.colors.mapLandDark}
              strokeWidth="5"
            />
          </g>
          <g opacity="0.32" stroke={remotionTheme.colors.white} strokeWidth="4">
            <path d="M47 209h326" />
            <path d="M77 150h266" />
            <path d="M78 270h264" />
            <ellipse cx="210" cy="210" rx="86" ry="165" fill="none" />
            <ellipse cx="210" cy="210" rx="143" ry="165" fill="none" />
          </g>
        </g>
        <circle cx="160" cy="134" r="24" fill="#ffffff" opacity="0.24" />
        {showPin ? (
          <g
            transform={`translate(210 ${pinDrop + 61}) scale(${pinScale})`}
            style={{ transformOrigin: "210px 95px" }}
          >
            <path
              d="M0-65c-38 0-69 30-69 68 0 53 69 126 69 126S69 56 69 3c0-38-31-68-69-68Z"
              fill={remotionTheme.colors.red}
              stroke={remotionTheme.colors.ink}
              strokeWidth="9"
            />
            <circle cx="0" cy="2" r="24" fill={remotionTheme.colors.white} />
          </g>
        ) : null}
      </svg>
    </div>
  );
}
