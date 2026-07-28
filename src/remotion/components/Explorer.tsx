import { remotionTheme } from "../styles/theme";

export type ExplorerPose =
  | "confident"
  | "thinking"
  | "excited"
  | "shocked"
  | "facepalm"
  | "celebrating"
  | "sneaking";

type ExplorerProps = {
  pose: ExplorerPose;
  frame: number;
  width?: number;
  showMap?: boolean;
};

const glove = "#fff8e7";
const boot = "#2f2828";
const arm = "#f2c94c";
const hat = "#f2c94c";
const hatDark = "#c99825";

function mouthPath(pose: ExplorerPose) {
  if (pose === "shocked") {
    return <ellipse cx="165" cy="178" rx="12" ry="17" fill={remotionTheme.colors.ink} />;
  }

  if (pose === "facepalm") {
    return (
      <path
        d="M143 194c13-8 32-8 45 0"
        stroke={remotionTheme.colors.ink}
        strokeWidth="6"
        fill="none"
        strokeLinecap="round"
      />
    );
  }

  if (pose === "thinking" || pose === "sneaking") {
    return (
      <path
        d="M141 191c13-6 33-4 47 3"
        stroke={remotionTheme.colors.ink}
        strokeWidth="6"
        fill="none"
        strokeLinecap="round"
      />
    );
  }

  return (
    <path
      d="M138 184c15 20 40 20 55 0"
      stroke={remotionTheme.colors.ink}
      strokeWidth="7"
      fill="none"
      strokeLinecap="round"
    />
  );
}

export function Explorer({ pose, frame, width = 340, showMap = false }: ExplorerProps) {
  const idle = Math.sin(frame / 8) * 4;
  const lean =
    pose === "confident"
      ? -3
      : pose === "sneaking"
        ? -8
        : pose === "excited" || pose === "celebrating"
          ? 6
          : pose === "shocked"
            ? 2
            : 0;
  const eyeShift = pose === "sneaking" ? -7 : pose === "thinking" ? 6 : pose === "celebrating" ? 2 : 0;
  const eyebrowTilt = pose === "shocked" ? -12 : pose === "confident" ? -5 : pose === "facepalm" ? 8 : 5;
  const hatY = pose === "facepalm" ? 18 : pose === "shocked" ? -6 : 0;
  const hatRotate = pose === "facepalm" ? -9 : pose === "celebrating" ? 5 : 0;
  const leftArm =
    pose === "celebrating" || pose === "excited"
      ? -132
      : pose === "sneaking"
        ? 22
        : pose === "thinking"
          ? -28
          : pose === "shocked"
            ? -6
            : -52;
  const rightArm =
    pose === "facepalm"
      ? -120
      : pose === "celebrating" || pose === "excited"
        ? 126
        : pose === "sneaking"
          ? 18
          : pose === "shocked"
            ? 6
            : 54;
  const mapRotation = pose === "thinking" ? 174 : pose === "confident" ? -13 : 4;

  return (
    <svg
      viewBox="0 0 330 390"
      width={width}
      height={Math.round(width * 1.18)}
      aria-hidden="true"
      style={{ overflow: "visible" }}
    >
      <g transform={`translate(0 ${idle}) rotate(${lean} 165 205)`}>
        <ellipse cx="165" cy="354" rx="96" ry="18" fill="rgba(5, 5, 5, 0.16)" />

        <path
          d="M120 282l-19 54"
          stroke={remotionTheme.colors.ink}
          strokeWidth="23"
          strokeLinecap="round"
        />
        <path d="M120 282l-19 54" stroke={arm} strokeWidth="13" strokeLinecap="round" />
        <path
          d="M209 282l20 54"
          stroke={remotionTheme.colors.ink}
          strokeWidth="23"
          strokeLinecap="round"
        />
        <path d="M209 282l20 54" stroke={arm} strokeWidth="13" strokeLinecap="round" />
        <path
          d="M78 330h54c6 11 3 22-10 30H55c1-15 8-25 23-30Z"
          fill={boot}
          stroke={remotionTheme.colors.ink}
          strokeWidth="7"
          strokeLinejoin="round"
        />
        <path
          d="M198 330h54c15 5 23 15 25 30h-68c-13-8-16-18-11-30Z"
          fill={boot}
          stroke={remotionTheme.colors.ink}
          strokeWidth="7"
          strokeLinejoin="round"
        />

        <g transform={`rotate(${leftArm} 82 190)`}>
          <path
            d="M82 190c-32 23-51 52-57 87"
            stroke={remotionTheme.colors.ink}
            strokeWidth="29"
            strokeLinecap="round"
            fill="none"
          />
          <path d="M82 190c-32 23-51 52-57 87" stroke={arm} strokeWidth="17" strokeLinecap="round" fill="none" />
          <circle cx="25" cy="279" r="18" fill={glove} stroke={remotionTheme.colors.ink} strokeWidth="7" />
          <path d="M15 271c9 5 18 5 28 0" stroke={remotionTheme.colors.line} strokeWidth="3" strokeLinecap="round" />
        </g>

        <g transform={`rotate(${rightArm} 248 190)`}>
          <path
            d="M248 190c32 23 51 52 57 87"
            stroke={remotionTheme.colors.ink}
            strokeWidth="29"
            strokeLinecap="round"
            fill="none"
          />
          <path d="M248 190c32 23 51 52 57 87" stroke={arm} strokeWidth="17" strokeLinecap="round" fill="none" />
          <circle cx="305" cy="279" r="18" fill={glove} stroke={remotionTheme.colors.ink} strokeWidth="7" />
          <path d="M294 271c9 5 19 5 29 0" stroke={remotionTheme.colors.line} strokeWidth="3" strokeLinecap="round" />
        </g>

        <circle cx="165" cy="176" r="101" fill={remotionTheme.colors.white} opacity="0.9" />
        <circle
          cx="165"
          cy="176"
          r="92"
          fill={remotionTheme.colors.ocean}
          stroke={remotionTheme.colors.ink}
          strokeWidth="9"
        />

        <defs>
          <clipPath id="map-promo-globe-mascot-clip">
            <circle cx="165" cy="176" r="86" />
          </clipPath>
        </defs>
        <g clipPath="url(#map-promo-globe-mascot-clip)">
          <path
            d="M76 154c22-31 68-36 87-16 14 14 3 33 21 47 21 17 54 1 70 22 14 19-1 53-29 62-32 10-68-16-87-43-14-20-18-43-40-45-13-2-23 5-34 0-15-7-13-19 12-27Z"
            fill={remotionTheme.colors.mapLand}
            stroke={remotionTheme.colors.mapLandDark}
            strokeWidth="5"
          />
          <path
            d="M199 108c38-15 82 7 91 39 7 27-14 52-39 55-17 2-23-9-42-6-19 4-30 17-44 9-14-8-15-31-5-50 9-18 22-40 39-47Z"
            fill={remotionTheme.colors.mapLand}
            stroke={remotionTheme.colors.mapLandDark}
            strokeWidth="5"
          />
          <path
            d="M155 239c24-10 56-4 70 16 14 18 6 43-14 55-25 15-66 3-78-23-10-20 2-39 22-48Z"
            fill={remotionTheme.colors.mapLand}
            stroke={remotionTheme.colors.mapLandDark}
            strokeWidth="5"
          />
          <g opacity="0.3" stroke={remotionTheme.colors.white} strokeWidth="4" fill="none">
            <path d="M78 176h174" />
            <path d="M92 136h148" />
            <path d="M92 216h148" />
            <ellipse cx="165" cy="176" rx="43" ry="87" />
            <ellipse cx="165" cy="176" rx="74" ry="87" />
          </g>
        </g>

        <path
          d="M119 260c28 17 65 17 92 0l-7 28c-25 12-53 12-78 0Z"
          fill={remotionTheme.colors.red}
          stroke={remotionTheme.colors.ink}
          strokeWidth="7"
          strokeLinejoin="round"
        />
        <circle cx="143" cy="274" r="8" fill={remotionTheme.colors.ink} />
        <circle cx="187" cy="274" r="8" fill={remotionTheme.colors.ink} />

        <g>
          <path d={`M122 ${144 + eyebrowTilt}l31-6`} stroke={remotionTheme.colors.ink} strokeWidth="6" strokeLinecap="round" />
          <path d={`M178 ${138 - eyebrowTilt}l31 6`} stroke={remotionTheme.colors.ink} strokeWidth="6" strokeLinecap="round" />
          <circle cx={142 + eyeShift} cy="162" r={pose === "shocked" ? 9 : 7} fill={remotionTheme.colors.ink} />
          <circle cx={188 + eyeShift} cy="162" r={pose === "shocked" ? 9 : 7} fill={remotionTheme.colors.ink} />
          <circle cx="125" cy="182" r="9" fill="#ffffff" opacity="0.22" />
          <circle cx="206" cy="182" r="9" fill="#ffffff" opacity="0.22" />
          {mouthPath(pose)}
        </g>

        {pose === "facepalm" ? (
          <g transform="rotate(-8 165 172)">
            <path
              d="M103 168c34-18 89-19 123-2"
              stroke={remotionTheme.colors.ink}
              strokeWidth="27"
              strokeLinecap="round"
            />
            <path d="M106 168c33-17 84-18 116-2" stroke={glove} strokeWidth="17" strokeLinecap="round" />
            <path d="M121 158l10 26M143 153l4 29M166 152v29M188 154l-5 28M209 158l-12 25" stroke={remotionTheme.colors.line} strokeWidth="3" strokeLinecap="round" />
          </g>
        ) : null}

        <g transform={`translate(0 ${hatY}) rotate(${hatRotate} 165 82)`}>
          <path
            d="M93 75c20-49 122-49 144 0l-20 29H113Z"
            fill={hat}
            stroke={remotionTheme.colors.ink}
            strokeWidth="8"
            strokeLinejoin="round"
          />
          <path d="M113 84h107" stroke={hatDark} strokeWidth="15" strokeLinecap="round" />
          <path
            d="M61 99c50 19 158 19 208 0"
            stroke={remotionTheme.colors.ink}
            strokeWidth="20"
            strokeLinecap="round"
          />
          <path d="M67 93c48 15 149 15 197 0" stroke={hat} strokeWidth="11" strokeLinecap="round" />
          <path d="M143 44c7-9 37-9 45 0" stroke="#fff1ad" strokeWidth="7" strokeLinecap="round" opacity="0.8" />
        </g>

        {showMap ? (
          <g transform={`translate(31 226) rotate(${mapRotation})`}>
            <path
              d="M0 0l76 14 67-14v76l-67 14L0 76Z"
              fill={remotionTheme.colors.cream}
              stroke={remotionTheme.colors.ink}
              strokeWidth="6"
              strokeLinejoin="round"
            />
            <path d="M76 14v76M38 7v76M110 7v76" stroke={remotionTheme.colors.line} strokeWidth="4" />
            <path
              d="M18 48c22-19 45-2 71-19 14-9 22-17 36-14"
              stroke={remotionTheme.colors.ocean}
              strokeWidth="5"
              fill="none"
              strokeLinecap="round"
            />
            <circle cx="101" cy="29" r="7" fill={remotionTheme.colors.red} stroke={remotionTheme.colors.ink} strokeWidth="3" />
          </g>
        ) : null}
      </g>
    </svg>
  );
}
