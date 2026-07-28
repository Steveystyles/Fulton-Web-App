import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";
import type { LayoutMetrics } from "../utils/layout";

type SceneBackgroundProps = {
  frame: number;
  metrics: LayoutMetrics;
  variant?: "light" | "dark" | "map";
};

export function SceneBackground({ frame, metrics, variant = "light" }: SceneBackgroundProps) {
  const isDark = variant === "dark";
  const dotOpacity = isDark ? 0.1 : 0.22;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: isDark
          ? `radial-gradient(circle at 50% 10%, rgba(215, 25, 32, 0.34), transparent ${metrics.isVertical ? 620 : 760}px), ${remotionTheme.colors.black}`
          : variant === "map"
            ? `linear-gradient(180deg, ${remotionTheme.colors.cream}, #dff4ff)`
            : `radial-gradient(circle at 18% 8%, rgba(215, 25, 32, 0.16), transparent ${metrics.isVertical ? 440 : 620}px), linear-gradient(180deg, ${remotionTheme.colors.cream}, ${remotionTheme.colors.paper})`,
      }}
    >
      {Array.from({ length: 16 }).map((_, index) => {
        const size = 24 + (index % 4) * 12;
        const edgePadding = metrics.isVertical ? 78 : 64;
        const availableWidth = Math.max(1, metrics.width - edgePadding * 2 - size);
        const availableHeight = Math.max(1, metrics.height - edgePadding * 2 - size);
        const x = edgePadding + ((index * 137) % availableWidth);
        const y = edgePadding + ((index * 89) % availableHeight);
        const drift = Math.sin((frame + index * 11) / 28) * 14;
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size,
              border: `4px solid ${isDark ? remotionTheme.colors.white : remotionTheme.colors.red}`,
              borderRadius: index % 3 === 0 ? remotionTheme.radius.pill : 9,
              opacity: dotOpacity,
              rotate: `${frame * 0.12 + index * 19}deg`,
              translate: `${drift}px ${Math.cos((frame + index * 7) / 24) * 9}px`,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          right: -120,
          bottom: -90,
          width: metrics.isVertical ? 460 : 620,
          height: metrics.isVertical ? 460 : 620,
          borderRadius: remotionTheme.radius.pill,
          background: isDark ? "rgba(255, 255, 255, 0.06)" : "rgba(215, 25, 32, 0.08)",
          scale: interpolate(Math.sin(frame / 45), [-1, 1], [0.96, 1.04]),
        }}
      />
    </div>
  );
}
