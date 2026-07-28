import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type SpeechBubbleProps = {
  frame: number;
  delay?: number;
  text: string;
  size?: "sm" | "md" | "lg";
  tail?: "left" | "right" | "top-left" | "top-right" | "bottom-left" | "bottom-right" | "none";
};

function tailStyle(tail: NonNullable<SpeechBubbleProps["tail"]>) {
  const base = {
    position: "absolute" as const,
    width: 36,
    height: 36,
    border: `6px solid ${remotionTheme.colors.ink}`,
    background: remotionTheme.colors.cream,
    rotate: "45deg",
    zIndex: 0,
  };

  if (tail === "left") {
    return {
      ...base,
      left: -21,
      top: "calc(50% - 18px)",
    };
  }

  if (tail === "right") {
    return {
      ...base,
      right: -21,
      top: "calc(50% - 18px)",
    };
  }

  if (tail === "top-left") {
    return {
      ...base,
      left: 58,
      top: -21,
    };
  }

  if (tail === "top-right") {
    return {
      ...base,
      right: 58,
      top: -21,
    };
  }

  if (tail === "bottom-right") {
    return {
      ...base,
      right: 58,
      bottom: -21,
    };
  }

  return {
    ...base,
    left: 58,
    bottom: -21,
  };
}

export function SpeechBubble({ frame, delay = 0, text, size = "md", tail = "bottom-left" }: SpeechBubbleProps) {
  const opacity = interpolate(frame, [delay, delay + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = interpolate(frame, [delay, delay + 10, delay + 18], [0.92, 1.03, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fontSize = size === "lg" ? 45 : size === "sm" ? 29 : 34;
  const maxWidth = size === "lg" ? 720 : size === "sm" ? 600 : 640;

  return (
    <div
      style={{
        position: "relative",
        display: "inline-flex",
        justifyContent: "center",
        minWidth: size === "sm" ? 430 : undefined,
        maxWidth,
        border: `6px solid ${remotionTheme.colors.ink}`,
        borderRadius: remotionTheme.radius.lg,
        padding: size === "lg" ? "24px 32px" : "18px 25px",
        background: remotionTheme.colors.cream,
        boxShadow: remotionTheme.shadow.card,
        color: remotionTheme.colors.ink,
        fontFamily: remotionTheme.fontFamily,
        fontSize,
        fontWeight: 900,
        lineHeight: 1.06,
        textAlign: "center",
        opacity,
        scale,
      }}
    >
      {tail === "none" ? null : <span style={tailStyle(tail)} />}
      <span style={{ position: "relative", zIndex: 1 }}>{text}</span>
    </div>
  );
}
