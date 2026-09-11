import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import postcss from "postcss";
import ts from "typescript";

// These are markup and structural layout contracts, not browser pixel tests.
// Nothing here opens an HTTP listener, calls an API, or reads account data.
const projectRoot = fileURLToPath(new URL("../", import.meta.url));
let vite;
let DailyQuiz;
let Card;
const originalFetch = globalThis.fetch;

before(async () => {
  globalThis.fetch = async () => { throw new Error("Layout contracts must not make network requests"); };
  vite = await createServer({
    root: projectRoot,
    logLevel: "error",
    server: { middlewareMode: true, hmr: false, watch: null },
    appType: "custom",
  });
  ({ DailyQuiz } = await vite.ssrLoadModule("/src/components/DailyQuiz.tsx"));
  ({ Card } = await vite.ssrLoadModule("/src/components/Card.tsx"));
});

after(async () => {
  await vite?.close();
  globalThis.fetch = originalFetch;
});

function classesFrom(tag) {
  return new Set((tag.match(/\bclass="([^"]*)"/)?.[1] ?? "").split(/\s+/));
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[character]);
}

test("quiz markup: four long answers are fully rendered in an equal two-column grid", () => {
  const answerTexts = [
    "The Royal Society for the Encouragement of Arts, Manufactures and Commerce",
    "A very long answer mentioning rivers, railway stations, mountains and several other landmarks",
    "The United Kingdom's Museum of Science & Industry (Manchester, England)",
    "AnExtremelyLongUnbrokenAnswerThatMustWrapWithoutMakingTheQuizWiderThanThePhone",
  ];
  const html = renderToStaticMarkup(createElement(DailyQuiz, {
    category: "general", storageScope: 0, quizDate: "2026-09-10", practice: true,
    questions: [{ id: "layout-question", question: "Which of these long answers is correct?", difficulty: "hard", answers: answerTexts.map((text, index) => ({ id: `answer-${index}`, text })) }],
    loading: false, error: null, serverResult: null, serverAnswers: [], onRefresh() {},
  }));
  const group = html.match(/<div\b[^>]*\brole="group"[^>]*\baria-label="Answer choices"[^>]*>/)?.[0];
  assert.ok(group, "answer choices have an accessible group label");
  const gridClasses = classesFrom(group);
  assert.ok(gridClasses.has("grid"));
  assert.ok(gridClasses.has("grid-cols-[repeat(2,minmax(0,1fr))]"), "both columns may shrink without horizontal overflow");
  assert.ok(gridClasses.has("auto-rows-fr"), "both rows share available answer height");

  const options = [...html.matchAll(/<button\b[^>]*\baria-pressed="(?:true|false)"[^>]*>[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.equal(options.length, 4, "all four options are present at the same time");
  options.forEach((option, index) => {
    assert.ok(option.includes(escapeHtml(answerTexts[index])), `answer ${index + 1} keeps its complete text`);
    const classes = classesFrom(option);
    assert.ok(classes.has("min-h-20"), "answer buttons retain at least an 80px minimum height");
    assert.ok(classes.has("min-w-0"));
    assert.ok(option.includes("whitespace-normal"));
    assert.ok(option.includes("[overflow-wrap:anywhere]"));
    assert.match(option, /aria-pressed="false"/, "unselected answers expose their state");
    assert.doesNotMatch(option, /\b(?:truncate|text-ellipsis|whitespace-nowrap|line-clamp-\d+)\b/, "answer text is not clipped or clamped");
  });
});

function visit(node, predicate, result = []) {
  if (predicate(node)) result.push(node);
  ts.forEachChild(node, child => { visit(child, predicate, result); });
  return result;
}

async function sourceTree(relativePath) {
  const source = await readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");
  return ts.createSourceFile(relativePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function attribute(node, name) {
  const opening = ts.isJsxElement(node) ? node.openingElement : node;
  const value = opening.attributes?.properties.find(item => ts.isJsxAttribute(item) && item.name.text === name)?.initializer;
  return value && ts.isStringLiteral(value) ? value.text : undefined;
}

function elements(node) {
  return visit(node, item => ts.isJsxElement(item) || ts.isJsxSelfClosingElement(item));
}

test("Wordle structure: help lives in a modal, not an extra details row above the board", async () => {
  const tree = await sourceTree("src/pages/Wordle.tsx");
  const all = elements(tree);
  assert.equal(all.filter(node => ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === "details" && /How to play Wordle/.test(node.getText(tree))).length, 0);
  const trigger = all.find(node => attribute(node, "aria-label") === "How to play Wordle");
  assert.ok(trigger, "help stays discoverable from its labeled button");
  assert.equal(attribute(trigger, "aria-haspopup"), "dialog");
  const dialog = all.find(node => attribute(node, "id") === "wordle-help-dialog");
  assert.ok(dialog);
  assert.equal(attribute(dialog, "role"), "dialog");
  assert.equal(attribute(dialog, "aria-modal"), "true");
  let ancestor = dialog.parent;
  while (ancestor && !(ts.isJsxElement(ancestor) && ancestor.openingElement.tagName.getText(tree) === "DialogPortal")) ancestor = ancestor.parent;
  assert.ok(ancestor, "help reuses the focus-trapping, focus-restoring portal");
});

async function stylesheet() {
  return postcss.parse(await readFile(new URL("../src/styles/index.css", import.meta.url), "utf8"));
}

function rulesFor(css, selector) {
  const matches = [];
  css.walkRules(rule => { if (rule.selectors.includes(selector)) matches.push(rule); });
  return matches;
}

function values(rules, property) {
  return rules.flatMap(rule => rule.nodes.filter(node => node.type === "decl" && node.prop === property).map(node => node.value));
}

test("CSS structure: app roots can shrink and disallow page-level horizontal scrolling", async () => {
  const css = await stylesheet();
  for (const selector of ["html", "body", "#root"]) {
    const rules = rulesFor(css, selector);
    assert.equal(values(rules, "min-width").at(-1), "0", `${selector} must not force a minimum viewport width`);
    const overflow = values(rules, "overflow-x");
    assert.ok(overflow.includes("hidden"), `${selector} retains the older-browser fallback`);
    assert.equal(overflow.at(-1), "clip", `${selector} prevents horizontal page scrolling`);
  }
});

test("Card markup and CSS structure: default padding allows explicit p-0 overrides", async () => {
  const html = renderToStaticMarkup(createElement(Card, { className: "p-0" }, "Layout fixture"));
  const classes = classesFrom(html);
  assert.ok(classes.has("saints-card-padding"));
  assert.ok(classes.has("p-0"));
  assert.ok(!classes.has("p-4"), "default padding is not a competing utility class");
  const rules = rulesFor(await stylesheet(), ".saints-card-padding");
  assert.ok(rules.some(rule => rule.parent.type === "atrule" && rule.parent.name === "layer" && rule.parent.params === "components"), "default padding belongs in the overridable component layer");
  assert.ok(rules.some(rule => values([rule], "padding").includes("1rem") || rule.nodes.some(node => node.type === "atrule" && node.name === "apply" && node.params.split(/\s+/).includes("p-4"))));
});

test("Map structure: tools and pin review sit outside the map viewport and use normal flow", async () => {
  const tree = await sourceTree("src/pages/MapGame.tsx");
  const all = elements(tree);
  const withClass = name => all.find(node => attribute(node, "className")?.split(/\s+/).includes(name));
  const viewport = withClass("map-viewport");
  assert.ok(viewport);
  for (const name of ["map-tools", "map-pin-review"]) {
    const element = withClass(name);
    assert.ok(element, `${name} is present`);
    assert.ok(!elements(viewport).includes(element), `${name} is not an overlay inside the map viewport`);
    assert.doesNotMatch(attribute(element, "className"), /\b(?:absolute|fixed)\b/);
    assert.ok(values(rulesFor(await stylesheet(), `.${name}`), "position").every(value => !["absolute", "fixed"].includes(value)));
  }
});

test("Map CSS structure: default mobile height is larger and an expanded mode exists", async () => {
  const css = await stylesheet();
  const mapHeights = values(rulesFor(css, ".map-stage"), "height");
  const mobileClamp = mapHeights[0]?.match(/^clamp\((\d+)px,\s*(\d+)[sd]vh,\s*(\d+)px\)$/);
  assert.ok(mobileClamp, "default mobile map height has bounded viewport-responsive sizing");
  assert.ok(Number(mobileClamp[1]) >= 300, "mobile map is at least 300px tall");
  assert.ok(Number(mobileClamp[2]) >= 50, "mobile map uses at least half the viewport height where space allows");
  const expanded = [];
  css.walkRules(rule => { if (/\[data-expanded\s*=\s*["']?true["']?\].*\.map-stage/.test(rule.selector)) expanded.push(rule); });
  assert.ok(values(expanded, "height").length, "Larger map has a dedicated size rule");
  const desktopExpanded = expanded.filter(rule => rule.parent.type === "atrule" && rule.parent.params === "(min-width: 760px)");
  assert.ok(values(desktopExpanded, "min-height").includes("620px"), "expanding a desktop map cannot shrink it on short screens");
});

test("Map structure: locking and changing a pin waits for pending lookups and clue reveals", async () => {
  const tree = await sourceTree("src/pages/MapGame.tsx");
  const declarations = visit(tree, ts.isVariableDeclaration);
  const busy = declarations.find(node => node.name.getText(tree) === "selectionBusy");
  assert.equal(busy?.initializer?.getText(tree), "snapLoading || submitting || revealing");
  const review = elements(tree).find(node => attribute(node, "className")?.split(/\s+/).includes("map-pin-review"));
  assert.ok(review);
  for (const button of elements(review).filter(node => ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === "button")) {
    const disabled = button.openingElement.attributes.properties.find(item => ts.isJsxAttribute(item) && item.name.text === "disabled");
    assert.equal(disabled?.initializer?.getText(tree), "{selectionBusy}");
  }
  const submit = declarations.find(node => node.name.getText(tree) === "submitSelectedGuess");
  const guard = visit(submit, ts.isIfStatement)[0];
  assert.ok(visit(guard.expression, ts.isIdentifier).some(node => node.text === "snapLoading"), "submission handler also rejects a pending replacement lookup");
});
