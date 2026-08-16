# Remotion Map Game Promo

This branch is an isolated, render-only Remotion promotional animation for the map-based location guessing game. The Remotion entry point is `src/remotion/index.ts`, and all source lives under `src/remotion/`.

## Start Remotion Studio

```bash
npm run remotion:studio
```

The registered compositions are:

- `MapGamePromo` at 1920 x 1080
- `MapGamePromoSquare` at 1080 x 1080
- `MapGamePromoVertical` at 1080 x 1920

## Edit Clues and Location

Change the typed data object in:

```text
src/remotion/data/defaultGamePromoData.ts
```

The fourth clue is the answer reveal and must match `locationName`. The score sequence is fixed at 10, 7, 5, and 2 points. The final call to action links to the live `/map` route.

The same object is passed through Remotion `defaultProps`, so it can also be edited from Remotion Studio.

## Change Branding

Shared animation colors, radius values, shadows, and the font loader are in:

```text
src/remotion/styles/theme.ts
```

The animation reuses the website's black, white, red, soft card shadows, rounded corners, and Inter/system typography. The final scene uses the existing public `favicon.svg` crest.

## Audio Assets

Audio files belong in:

```text
public/audio/
```

The included WAV files are generated placeholder tones documented in `public/audio/README.md`. Replace them with licensed production audio using the same filenames, or update `src/remotion/components/Soundtrack.tsx`.

If an optional audio file is missing, the soundtrack skips it instead of mounting a broken `<Audio>` tag.

## Preview Each Format

Open Studio with:

```bash
npm run remotion:studio
```

Then select `MapGamePromo`, `MapGamePromoSquare`, or `MapGamePromoVertical` in the left panel.

## Render MP4 Files

```bash
npm run remotion:render:landscape
npm run remotion:render:square
npm run remotion:render:vertical
```

Outputs:

```text
out/map-game-promo-landscape.mp4
out/map-game-promo-square.mp4
out/map-game-promo-vertical.mp4
```

The scripts render H.264 MP4 with CRF 20 for website-friendly quality.

## Transparent WebM

This design uses full-frame backgrounds, so transparency is not enabled by default. If you later adapt the scenes to transparent backgrounds, render a VP9 WebM with:

```bash
npx remotion render src/remotion/index.ts MapGamePromo out/map-game-promo-transparent.webm --image-format=png --pixel-format=yuva420p --codec=vp9
```

## Website Delivery

This worktree does not contain or deploy the website. Render new working media into `out/`, review it, then copy an approved final asset into the consuming project. The existing files under `public/videos/` are retained delivery artifacts, not build inputs.

## Validation

Run:

```bash
npm run test:remotion
npm run build
npm run remotion:still
```

The still render writes:

```text
out/map-game-promo-smoke.png
```
