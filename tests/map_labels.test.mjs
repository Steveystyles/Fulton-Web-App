import assert from "node:assert/strict";
import { test } from "node:test";
import { layoutMapLabels } from "../src/lib/mapLabels.ts";

function candidate(id, overrides = {}) {
  return { id, name: `Place ${id}`, x: 180, y: 200, width: 82, height: 24, priority: 1, ...overrides };
}

function box(label) {
  return { left: label.left, top: label.top, right: label.left + label.width, bottom: label.top + label.height };
}

function assertSeparated(a, b) {
  assert.ok(a.right + 6 <= b.left || b.right + 6 <= a.left
    || a.bottom + 6 <= b.top || b.bottom + 6 <= a.top,
  `Boxes should have at least a 6px gap: ${JSON.stringify({ a, b })}`);
}

function assertLayout(labels, viewport, reserved = []) {
  assert.ok(labels.length <= 6);
  labels.forEach((label, index) => {
    const bounds = box(label);
    assert.ok(Object.values(bounds).every(Number.isFinite));
    assert.ok(bounds.left >= 8 && bounds.top >= 8);
    assert.ok(bounds.right <= viewport.width - 8 && bounds.bottom <= viewport.height - 8);
    labels.slice(index + 1).forEach((other) => assertSeparated(bounds, box(other)));
    reserved.forEach((other) => assertSeparated(bounds, other));
  });
}

test("repeated London labels are normalized and only the highest priority survives", () => {
  const labels = layoutMapLabels([
    candidate(1, { name: "London", priority: 1 }),
    candidate(2, { name: "  LONDON  ", priority: 3 }),
    candidate(3, { name: "london", priority: 2 }),
    candidate(4, { name: "Tower  of\nLondon", x: 190, priority: 2 }),
    candidate(5, { name: " Tower of London ", priority: 1 }),
  ], { width: 360, height: 420 });
  assert.deepEqual(labels.map((label) => label.id), [2, 4]);
  assertLayout(labels, { width: 360, height: 420 });
});

test("nearby distinct names never overlap even when most must be hidden", () => {
  const viewport = { width: 360, height: 420 };
  const labels = layoutMapLabels(Array.from({ length: 18 }, (_, index) => candidate(index, {
    x: 180 + index % 3, y: 200 + index % 4,
  })), viewport);
  assert.ok(labels.length > 0 && labels.length < 18);
  assertLayout(labels, viewport);
});

test("markers and map controls reserve space before place labels", () => {
  const viewport = { width: 360, height: 420 };
  const reserved = [
    { left: 164, top: 182, right: 196, bottom: 218 },
    { left: 130, top: 130, right: 225, bottom: 170 },
  ];
  const labels = layoutMapLabels([candidate(1), candidate(2, { x: 230, y: 160 })], viewport, reserved);
  assert.ok(labels.length > 0);
  assertLayout(labels, viewport, reserved);
});

test("edge anchors use the side that fits and all text stays inside the viewport", () => {
  const viewport = { width: 360, height: 420 };
  const labels = layoutMapLabels([
    candidate(1, { x: 0, y: 100 }),
    candidate(2, { x: 360, y: 200 }),
    candidate(3, { x: 150, y: 0 }),
    candidate(4, { x: 200, y: 420 }),
  ], viewport);
  assert.equal(labels.length, 4);
  assertLayout(labels, viewport);
});

test("a viewport narrower than 320px remains usable without horizontal spill", () => {
  const viewport = { width: 240, height: 280 };
  const labels = layoutMapLabels([
    candidate(1, { x: 120, y: 90, width: 200 }),
    candidate(2, { x: 120, y: 180, width: 170 }),
  ], viewport);
  assert.equal(labels.length, 2);
  assertLayout(labels, viewport);
});

test("oversized text is hidden rather than clipped or moved away from its anchor", () => {
  const viewport = { width: 280, height: 300 };
  const labels = layoutMapLabels([
    candidate(1, { name: "A very long landmark name".repeat(10), x: 140, width: 1000 }),
    candidate(2, { x: 140 }),
  ], viewport);
  assert.deepEqual(labels.map((label) => label.id), [2]);
  assertLayout(labels, viewport);
});

test("offscreen anchors are dropped even if their label might extend into view", () => {
  const labels = layoutMapLabels([
    candidate(1, { x: -1 }), candidate(2, { x: 361 }),
    candidate(3, { y: -1 }), candidate(4, { y: 421 }),
  ], { width: 360, height: 420 });
  assert.deepEqual(labels, []);
});

test("invalid candidate geometry and empty names cannot produce invalid positions", () => {
  const viewport = { width: 360, height: 420 };
  const invalid = [
    { x: NaN }, { y: Infinity }, { width: 0 }, { height: -2 },
    { width: Infinity }, { priority: NaN }, { id: Infinity }, { name: " \n " },
  ];
  const labels = layoutMapLabels([
    ...invalid.map((overrides, index) => candidate(index, overrides)), candidate(100),
  ], viewport, [{ left: NaN, top: 0, right: 4, bottom: 4 }]);
  assert.deepEqual(labels.map((label) => label.id), [100]);
  assertLayout(labels, viewport);
});

test("unusable viewports and completely reserved maps hide every label", () => {
  for (const viewport of [
    { width: 16, height: 300 }, { width: 300, height: 0 },
    { width: Infinity, height: 300 }, { width: 300, height: NaN },
  ]) assert.deepEqual(layoutMapLabels([candidate(1)], viewport), []);

  assert.deepEqual(layoutMapLabels([candidate(1)], { width: 360, height: 420 }, [
    { left: 0, top: 0, right: 360, bottom: 420 },
  ]), []);
});

test("priority and ascending ID ties are deterministic regardless of input order", () => {
  const candidates = [candidate(3), candidate(1), candidate(2, { priority: 2 })];
  const first = layoutMapLabels(candidates, { width: 360, height: 420 });
  assert.deepEqual(first.map((label) => label.id), [2, 1, 3]);
  assert.deepEqual(layoutMapLabels([...candidates].reverse(), { width: 360, height: 420 }), first);
});

test("the map has a maximum of six visible labels even when there is ample room", () => {
  const viewport = { width: 1000, height: 1000 };
  const labels = layoutMapLabels(Array.from({ length: 12 }, (_, index) => candidate(index, {
    x: 100 + (index % 4) * 200, y: 100 + Math.floor(index / 4) * 250,
  })), viewport);
  assert.equal(labels.length, 6);
  assertLayout(labels, viewport);
});

test("layout does not mutate candidates, viewport, or reserved rectangles", () => {
  const candidates = Object.freeze([
    Object.freeze(candidate(2)), Object.freeze(candidate(1, { priority: 2 })),
  ]);
  const viewport = Object.freeze({ width: 360, height: 420 });
  const reserved = Object.freeze([Object.freeze({ left: 0, top: 0, right: 20, bottom: 20 })]);
  const before = JSON.stringify({ candidates, viewport, reserved });
  const labels = layoutMapLabels(candidates, viewport, reserved);
  assert.equal(JSON.stringify({ candidates, viewport, reserved }), before);
  assert.notEqual(labels[0], candidates[1]);
});
