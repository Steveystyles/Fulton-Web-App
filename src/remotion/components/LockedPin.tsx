import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type LockedPinProps = {
  frame: number;
  start: number;
  x: number;
  y: number;
};

export function LockedPin({ frame, start, x, y }: LockedPinProps) {
  const age = frame - start;
  if (age < 0) {
    return null;
  }

  const pulse = interpolate(age, [10, 42], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const lockDrop = interpolate(age, [23, 34], [-52, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <g transform={`translate(${x} ${y})`}>
      <circle
        cx="0"
        cy="0"
        r={34 + pulse * 82}
        fill="none"
        stroke={remotionTheme.colors.green}
        strokeWidth="8"
        opacity={Math.max(0, 0.45 - pulse * 0.45)}
      />
      <g transform={`translate(0 ${lockDrop - 98})`}>
        <rect x="-38" y="-2" width="76" height="54" rx="14" fill={remotionTheme.colors.ink} />
        <path d="M-23-2v-20c0-30 46-30 46 0v20" fill="none" stroke={remotionTheme.colors.ink} strokeWidth="14" strokeLinecap="round" />
        <circle cx="0" cy="24" r="8" fill={remotionTheme.colors.yellow} />
      </g>
    </g>
  );
}
