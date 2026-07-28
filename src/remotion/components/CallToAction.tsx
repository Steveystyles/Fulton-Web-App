import { interpolate } from "remotion";
import { remotionTheme } from "../styles/theme";

type CallToActionProps = {
  frame: number;
  label: string;
  secondary: string;
  url?: string;
};

export function CallToAction({ frame, label, secondary, url }: CallToActionProps) {
  const pulse = interpolate(Math.sin(frame / 14), [-1, 1], [0.98, 1.03]);

  return (
    <div style={{ textAlign: "center", fontFamily: remotionTheme.fontFamily }}>
      <div
        style={{
          display: "inline-flex",
          minHeight: 92,
          alignItems: "center",
          justifyContent: "center",
          border: `7px solid ${remotionTheme.colors.ink}`,
          borderRadius: remotionTheme.radius.pill,
          padding: "22px 46px",
          background: remotionTheme.colors.red,
          boxShadow: remotionTheme.shadow.red,
          color: remotionTheme.colors.white,
          fontSize: 40,
          fontWeight: 950,
          scale: pulse,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <p
        style={{
          margin: "24px 0 0",
          color: remotionTheme.colors.white,
          fontSize: 34,
          fontWeight: 850,
          textShadow: "0 3px 0 rgba(5, 5, 5, 0.28)",
        }}
      >
        {secondary}
      </p>
      {url ? (
        <p
          style={{
            margin: "10px 0 0",
            color: "rgba(255, 255, 255, 0.72)",
            fontSize: 24,
            fontWeight: 800,
          }}
        >
          {url}
        </p>
      ) : null}
    </div>
  );
}
