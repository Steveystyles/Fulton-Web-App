import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type MapPinProps = {
  frame: number;
  start: number;
  x: number;
  y: number;
  correct?: boolean;
  ocean?: boolean;
};

export function MapPin({ frame, start, x, y, correct = false, ocean = false }: MapPinProps) {
  const age = frame - start;
  if (age < 0) {
    return null;
  }

  const drop = interpolate(age, [0, 13, 20], [-64, 0, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const entranceOpacity = interpolate(age, [0, 7], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = interpolate(age, [11, 16, 24], [1, 0.76, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const wrongShake = !correct && age > 16 && age < 44 ? Math.sin(age * 2.2) * 9 : 0;
  const fade = !correct && age > 48 ? interpolate(age, [48, 70], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }) : 1;
  const fall = !correct && age > 42 ? interpolate(age, [42, 70], [0, ocean ? 90 : 42], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }) : 0;

  return (
    <g transform={`translate(${x} ${y + drop + fall}) rotate(${wrongShake}) scale(${scale})`} opacity={fade * entranceOpacity}>
      <path
        d="M0-60c-33 0-60 26-60 59 0 46 60 110 60 110S60 45 60-1c0-33-27-59-60-59Z"
        fill={correct ? remotionTheme.colors.green : remotionTheme.colors.red}
        stroke={remotionTheme.colors.ink}
        strokeWidth="8"
      />
      <circle cx="0" cy="-2" r="21" fill={remotionTheme.colors.white} />
      {!correct && age > 19 ? (
        <g stroke={remotionTheme.colors.white} strokeWidth="13" strokeLinecap="round">
          <path d="M-23-23L23 23" />
          <path d="M23-23L-23 23" />
        </g>
      ) : null}
      {ocean && age > 25 ? (
        <g fill="none" stroke={remotionTheme.colors.white} strokeWidth="5" opacity="0.8">
          <ellipse cx="0" cy="62" rx={interpolate(age, [25, 45], [20, 58], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })} ry="12" />
        </g>
      ) : null}
    </g>
  );
}
