import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { api } from "../src/lib/api.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
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
