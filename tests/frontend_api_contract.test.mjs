import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { api } from "../src/lib/api.ts";
import { mergeNewsItems } from "../src/lib/news.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("quiz load hydrates authoritative completion and progress", async () => {
  const result = { score: 6, correctCount: 2 };
  globalThis.fetch = async () => new Response(JSON.stringify({ date: "2026-09-09", questions: [], results: { football: result }, progress: { general: [{ questionId: "q1", choiceId: "a1" }] } }));
  const response = await api.dailyQuestions({ force: true });
  assert.deepEqual(response.results.football, result);
  assert.equal(response.progress.general[0].choiceId, "a1");
});

test("quiz confirmation saves ordered IDs, never answer text", async () => {
  let body;
  globalThis.fetch = async (input, init) => { assert.equal(input, "/api/daily-quiz/progress"); body = JSON.parse(init.body); return new Response(JSON.stringify({ answers: body.answers })); };
  const payload = { date: "2026-09-09", category: "football", answers: [{ questionId: "q1", choiceId: "a1" }] };
  await api.saveQuizProgress(payload);
  assert.deepEqual(body, payload);
});

test("newer news corrections win and older poll responses cannot roll them back", () => {
  const old = { id: 1, title: "Club score", source: "Club", publishedAt: "2026-09-09T10:00:00Z", updatedAt: "2026-09-09T10:00:00Z", summary: "1-0" };
  const update = { ...old, summary: "2-0", updatedAt: "2026-09-09T10:05:00Z" };
  assert.deepEqual(mergeNewsItems([old], [update]), [update]);
  assert.deepEqual(mergeNewsItems([update], [old]), [update]);
  assert.deepEqual(mergeNewsItems([old], [{ ...update, title: "Corrected club result" }]), [{ ...update, title: "Corrected club result" }]);
});

test("practice scoring uses a separate endpoint", async () => {
  globalThis.fetch = async (input) => { assert.equal(input, "/api/practice/quiz/result"); return new Response('{"result":{}}'); };
  await api.submitPracticeQuiz({ date: "2026-09-08", category: "general", answers: [] });
});

test("Wordle guesses send the concurrency and game-date guards", async () => {
  let capturedInput;
  let capturedInit;
  globalThis.fetch = async (input, init) => {
    capturedInput = input;
    capturedInit = init;
    return new Response("{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const payload = {
    guess: "crane",
    expectedAttemptsUsed: 2,
    expectedGameDate: "2026-08-21",
  };
  await api.submitWordleGuess(payload);

  assert.equal(capturedInput, "/api/wordle/guess");
  assert.equal(capturedInit?.method, "POST");
  assert.equal(capturedInit?.credentials, "include");
  assert.equal(new Headers(capturedInit?.headers).get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), payload);
});
