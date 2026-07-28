import type { ReactNode } from "react";
import { remotionTheme } from "../styles/theme";

export const mapCoordinates = {
  southAmerica: { x: 312, y: 416 },
  greenland: { x: 422, y: 154 },
  ocean: { x: 578, y: 421 },
  kathmandu: { x: 714, y: 302 },
} as const;

type GameMapProps = {
  children?: ReactNode;
  showLabels?: boolean;
};

export function GameMap({ children, showLabels = true }: GameMapProps) {
  return (
    <svg viewBox="0 0 1000 620" width="100%" height="100%" aria-hidden="true" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="map-promo-ocean" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stopColor="#bfeaff" />
          <stop offset="100%" stopColor="#2d9cdb" />
        </linearGradient>
      </defs>
      <rect x="8" y="8" width="984" height="604" rx="46" fill="url(#map-promo-ocean)" stroke={remotionTheme.colors.ink} strokeWidth="12" />
      <g opacity="0.24" stroke={remotionTheme.colors.white} strokeWidth="3">
        {Array.from({ length: 8 }).map((_, index) => (
          <path key={`v-${index}`} d={`M${110 + index * 108} 18v584`} />
        ))}
        {Array.from({ length: 5 }).map((_, index) => (
          <path key={`h-${index}`} d={`M20 ${110 + index * 98}h960`} />
        ))}
      </g>
      <g fill={remotionTheme.colors.mapLand} stroke={remotionTheme.colors.ink} strokeWidth="8" strokeLinejoin="round">
        <path d="M125 178c52-65 154-76 217-33 43 29 37 80 80 111 49 35 116 9 153 58 34 45 5 109-56 130-73 25-148-34-194-89-35-42-52-88-103-89-37-1-56 25-91 10-39-17-37-60-6-98Z" />
        <path d="M384 70c73-46 162-25 192 28 26 46-8 105-63 116-37 8-59-9-91 7-32 15-45 54-78 43-34-12-39-65-22-108 13-33 33-68 62-86Z" />
        <path d="M612 165c68-60 177-42 221 31 37 61 14 141-49 165-56 21-86-20-137-1-45 17-55 66-99 55-50-13-65-82-44-139 16-44 56-86 108-111Z" />
        <path d="M665 438c45-37 111-22 132 21 20 40-10 91-57 98-47 6-93-33-95-75-1-17 6-32 20-44Z" />
      </g>
      <path
        d="M682 283l35-31 42 26-17 46-47 10Z"
        fill={remotionTheme.colors.yellow}
        stroke={remotionTheme.colors.ink}
        strokeWidth="7"
        strokeLinejoin="round"
      />
      {showLabels ? (
        <g fontFamily={remotionTheme.fontFamily} fontWeight="900" letterSpacing="0">
          <text x="680" y="253" fontSize="26" fill={remotionTheme.colors.ink}>NEPAL</text>
          <text x="738" y="306" fontSize="22" fill={remotionTheme.colors.ink}>Kathmandu</text>
          <text x="195" y="502" fontSize="24" fill={remotionTheme.colors.ink} opacity="0.66">South America?</text>
          <text x="348" y="96" fontSize="24" fill={remotionTheme.colors.ink} opacity="0.66">Greenland?</text>
          <text x="548" y="515" fontSize="24" fill={remotionTheme.colors.white} opacity="0.84">Definitely not here</text>
        </g>
      ) : null}
      {children}
    </svg>
  );
}
