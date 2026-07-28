export const remotionTheme = {
  fontFamily:
    'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  colors: {
    black: "#050505",
    ink: "#111114",
    charcoal: "#18181b",
    white: "#ffffff",
    paper: "#f4f4f1",
    mist: "#e9e9e4",
    line: "#d7d7d0",
    red: "#d71920",
    redDark: "#a90f18",
    redSoft: "#fff0f1",
    ocean: "#2d9cdb",
    sky: "#bfeaff",
    green: "#27ae60",
    yellow: "#f2c94c",
    amber: "#f59e0b",
    coral: "#eb5757",
    cream: "#fff8e7",
    mapLand: "#b8e3a4",
    mapLandDark: "#7bb978",
  },
  radius: {
    sm: 16,
    md: 24,
    lg: 42,
    pill: 999,
  },
  shadow: {
    card: "0 18px 42px rgba(5, 5, 5, 0.16)",
    heavy: "0 28px 70px rgba(5, 5, 5, 0.24)",
    red: "0 18px 38px rgba(215, 25, 32, 0.28)",
  },
  stroke: {
    thick: 10,
    regular: 6,
  },
} as const;

export type RemotionTheme = typeof remotionTheme;
