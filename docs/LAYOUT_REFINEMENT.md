# Game layout refinement

Follow-up to the mobile screenshot and game-layout feedback, September 2026.

- Map: more usable width, a taller responsive viewport and optional larger mode; duplicate place names and colliding labels are suppressed. Labels avoid pins, controls and edges. Controls and pin confirmation now sit below the map, with one confirmation action. Previous clues expand in normal flow. Desktop uses a clue/map split layout.
- Wordle: help opens from the existing settings row in the accessible dialog portal, leaving the board position unchanged. Existing focus trapping, Escape dismissal and focus restoration are reused.
- Quiz: all four complete answer texts appear in a two-by-two grid with wrapping, responsive type and generous targets. Long answers and enlarged text can still require vertical scrolling; answers are never truncated to force them onto one screen.
- Shared layout: reduce redundant card padding, allow content to shrink and wrap, prohibit page-level horizontal scrolling, and measure fixed header/navigation space. Map panning remains available inside the map viewport.

No game scoring, authentication, database schema, credentials or AI calls are changed.

## Verification

`npm run build`, `npm run test:client`, `npm run test:server` and `git diff --check` form the local gate, followed by the existing Linux CI and signed-image deployment gates.

The client suite covers API contracts, label collision geometry, real server-rendered quiz/Card markup, and structural CSS/JSX layout contracts. These are not browser pixel tests. Browser automation is unavailable in this environment; an actual mobile visual recheck and assistive-technology playthrough remain manual QA items.

The Windows server suite can skip the directory-symlink test because creating a symbolic link requires a privilege the account lacks. Linux CI must execute that test successfully; its assertions are unchanged.
