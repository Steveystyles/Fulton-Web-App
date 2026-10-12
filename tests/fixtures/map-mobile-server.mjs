// Local-only API fixture for checking every Map clue stage in a real browser.
// Run alongside `npm run dev`; Vite proxies /api to this server on port 8000.
import { createServer } from "node:http";

const stages = new Map([
  ["2026-10-10", 0],
  ["2026-10-11", 1],
  ["2026-10-12", 2],
  ["2026-10-13", 3],
]);
const clues = [
  { id: "hard", title: "Hard clue", maxPoints: 10, text: "Its architects brought the right to roam into the city: anyone can walk up the sloping roof, turning a performance venue into a public square. This extra sentence checks how a longer opening clue fits on a small phone." },
  { id: "medium", title: "Medium clue", maxPoints: 7, text: "In Oslo, Norway, this cultural venue rises from the waterfront at the edge of the Oslofjord. Its public space draws visitors even when no performance is scheduled." },
  { id: "easy", title: "Easy clue", maxPoints: 5, text: "In central Oslo, situated within the Bjørvika neighbourhood, this prominent waterfront landmark invites pedestrians to walk up its angled roof." },
  { id: "name", title: "Place name", maxPoints: 2, text: "Oslo Opera House", revealsName: true },
];

function respond(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(payload));
}

createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1:8000");
  if (url.pathname === "/api/auth/me") {
    respond(response, 200, { user: { id: 1, username: "Map QA", role: "user" }, availableAnnouncements: [], pendingAnnouncements: [] });
  } else if (url.pathname === "/api/health") {
    respond(response, 200, { ok: true, build: { version: "local-map-fixture" } });
  } else if (url.pathname === "/api/today") {
    respond(response, 200, { date: "2026-10-10", mapRoundDate: "2026-10-10", nextRoundAt: "2026-10-11T00:00:00Z", nextMapDates: [], activities: [
      { id: "wordle", title: "Wordle", href: "/wordle", status: "ready", score: null },
      { id: "quiz", title: "Quiz", href: "/quiz", status: "ready", score: null },
      { id: "map", title: "Map", href: "/map", status: "ready", score: null },
    ] });
  } else if (url.pathname === "/api/daily-map-game") {
    const date = url.searchParams.get("date") ?? "2026-10-10";
    const count = stages.get(date) ?? 0;
    respond(response, 200, { date, status: "published", maxScore: 10, completedLevels: 0, levels: [{
      id: 1, slug: "easy", title: "Place 1", clues: clues.slice(0, count + 1), mapAnchors: [],
      revealedHintCount: count, submitted: false,
    }] });
  } else if (url.pathname === "/api/daily-map-game/1/snap") {
    const selected = { selectionId: "local-fixture", point: { lat: 59.9075, lng: 10.753 }, clickedPoint: { lat: 59.9075, lng: 10.753 }, snapped: true, name: "Oslo Opera House", kind: "landmark", distanceMeters: 0, snapRadiusMeters: 500, countryCode: "NO", admin1: "Oslo", selectedIndex: 0 };
    respond(response, 200, { ...selected, alternatives: [selected, { ...selected, selectionId: "local-fixture-two", name: "Oslo Central Station", selectedIndex: 1 }] });
  } else {
    respond(response, 404, { error: "No local Map fixture for this API route." });
  }
}).listen(8000, "127.0.0.1", () => {
  process.stdout.write("Map fixture listening on http://127.0.0.1:8000\n");
});
