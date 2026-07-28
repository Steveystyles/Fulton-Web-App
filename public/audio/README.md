# Remotion Map Game Promo Audio

These WAV files are generated placeholder tones for the Remotion map game promo. They are original simple synthesized tones and are included so the composition can render with local audio and without depending on external services.

Replace them with licensed production audio as needed, keeping the same filenames or updating `src/remotion/components/Soundtrack.tsx`.

The `Soundtrack` component checks Remotion's static file manifest before mounting each audio clip, so missing optional audio files are skipped instead of crashing the render.
