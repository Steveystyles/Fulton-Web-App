# Fulton's Map Game Promo

This worktree is a render-only Remotion project for the Map Game promotional video. It intentionally contains no player API, production server, deployment scripts, or inherited website frontend.

## Setup

```bash
npm install
npm run remotion:studio
```

The Remotion entry point is `src/remotion/index.ts`. Studio exposes landscape, square, and vertical compositions.

## Validate

```bash
npm run build
npm run test:remotion
npm audit --audit-level=high
```

`npm run build` is a strict TypeScript check. Rendered files are written to the ignored `out/` directory.

## Render

```bash
npm run remotion:render:landscape
npm run remotion:render:square
npm run remotion:render:vertical
npm run remotion:still
```

Edit the typed promo data in `src/remotion/data/defaultGamePromoData.ts`. Branding and timing details are documented in [docs/remotion-map-game-promo.md](docs/remotion-map-game-promo.md).

The committed files under `public/videos/` are existing delivery assets. New working renders belong in `out/`; copy only deliberately approved final media into another project.
