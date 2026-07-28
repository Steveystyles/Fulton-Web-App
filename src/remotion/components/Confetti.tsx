import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";
import { seededRandom } from "../utils/animation";

type ConfettiProps = {
  frame: number;
  start: number;
  count?: number;
  originX?: number;
  originY?: number;
  seed?: number;
};

const confettiColors = [
  remotionTheme.colors.red,
  remotionTheme.colors.yellow,
  remotionTheme.colors.green,
  remotionTheme.colors.ocean,
  remotionTheme.colors.white,
];

export function Confetti({
  frame,
  start,
  count = 44,
  originX = 50,
  originY = 50,
  seed = 49,
}: ConfettiProps) {
  const age = frame - start;
  if (age < 0 || age > 72) {
    return null;
  }

  const rand = seededRandom(seed);
  const particles = Array.from({ length: count }).map((_, index) => {
    const angle = rand() * Math.PI * 2;
    const distance = 180 + rand() * 480;
    const drift = 60 + rand() * 150;
    const size = 12 + rand() * 22;
    const color = confettiColors[index % confettiColors.length];
    const progress = interpolate(age, [0, 55], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    const x = Math.cos(angle) * distance * progress;
    const y = Math.sin(angle) * distance * progress + drift * progress * progress;

    return (
      <div
        key={index}
        style={{
          position: "absolute",
          left: `${originX}%`,
          top: `${originY}%`,
          width: size,
          height: size * 0.46,
          borderRadius: 3,
          background: color,
          opacity: interpolate(age, [0, 16, 72], [0, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: `${x}px ${y}px`,
          rotate: `${age * (4 + rand() * 8)}deg`,
        }}
      />
    );
  });

  return <>{particles}</>;
}
