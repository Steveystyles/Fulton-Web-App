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
let QuizBoardGrid;
let Card;
let HelpButton;
let MapClueEditor;
let canApplyUpdateWithoutInterrupting;
let AppRecoveryBoundary;
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
  ({ QuizBoardGrid } = await vite.ssrLoadModule("/src/pages/Quiz.tsx"));
  ({ Card } = await vite.ssrLoadModule("/src/components/Card.tsx"));
  ({ HelpButton } = await vite.ssrLoadModule("/src/components/HelpButton.tsx"));
  ({ MapClueEditor } = await vite.ssrLoadModule("/src/components/MapClueEditor.tsx"));
  ({ canApplyUpdateWithoutInterrupting } = await vite.ssrLoadModule("/src/components/AppUpdateReloader.tsx"));
  ({ AppRecoveryBoundary } = await vite.ssrLoadModule("/src/components/AppRecoveryBoundary.tsx"));
});

after(async () => {
  await vite?.close();
  globalThis.fetch = originalFetch;
});

function classesFrom(tag) {
  return new Set((tag.match(/\bclass="([^"]*)"/)?.[1] ?? "").split(/\s+/));
}

test("new releases apply on idle screens without discarding games or form entries", () => {
  const emptyPage = {
    activeElement: null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  assert.equal(canApplyUpdateWithoutInterrupting("/", emptyPage), true);
  assert.equal(canApplyUpdateWithoutInterrupting("/scores", emptyPage), true);
  for (const path of ["/wordle", "/quiz", "/map", "/account", "/admin", "/ops"]) {
    assert.equal(canApplyUpdateWithoutInterrupting(path, emptyPage), false, path);
  }
  const username = { value: "admin", isContentEditable: false };
  assert.equal(canApplyUpdateWithoutInterrupting("/", {
    ...emptyPage, querySelectorAll: () => [username],
  }), false, "a filled login field must survive an update");
  assert.equal(canApplyUpdateWithoutInterrupting("/", {
    ...emptyPage, activeElement: username, querySelectorAll: () => [username],
  }), false, "a focused input must not reload while the user is typing");
  assert.equal(canApplyUpdateWithoutInterrupting("/", {
    ...emptyPage, querySelector: () => ({}),
  }), false, "an open dialog must not be interrupted");
});

test("a failed lazy route offers a visible reload instead of a blank page", () => {
  const boundary = new AppRecoveryBoundary({ children: createElement("p", null, "Loaded route") });
  assert.match(renderToStaticMarkup(boundary.render()), /Loaded route/);
  boundary.state = AppRecoveryBoundary.getDerivedStateFromError(new Error("Missing chunk"));
  const html = renderToStaticMarkup(boundary.render());
  assert.match(html, /role="alert"/);
  assert.match(html, /Couldn&#x27;t open this screen/);
  assert.match(html, /Reload page/);
  assert.doesNotMatch(html, /Missing chunk/);
});

test("help starts as a compact button with no instructions in the game layout", () => {
  const html = renderToStaticMarkup(createElement(HelpButton, { title: "Game help", compact: true }, "Hidden instructions"));
  assert.match(html, /aria-haspopup="dialog"/);
  assert.match(html, /aria-expanded="false"/);
  assert.doesNotMatch(html, /Hidden instructions|<details|role="dialog"/);
});

test("Map clue corrections live in the admin screen and begin with a date picker", async () => {
  const html = renderToStaticMarkup(createElement(MapClueEditor));
  assert.match(html, /Map clue editor/);
  assert.match(html, /type="date"/);
  assert.doesNotMatch(html, /Answer:/, "unloaded clues are not displayed by default");
  const adminSource = (await readFile(new URL("../src/pages/Admin.tsx", import.meta.url), "utf8"));
  assert.match(adminSource, /\{isAdmin \? <MapClueEditor \/> : null\}/);
});

test("Wordle Enter uses an accessible icon and map crosshair uses centred geometry", async () => {
  const wordle = await sourceTree("src/pages/Wordle.tsx");
  const enter = elements(wordle).find(node => attribute(node, "aria-label") === "Enter guess");
  assert.ok(enter);
  assert.match(enter.getText(wordle), /<CornerDownLeft/);
  const map = await sourceTree("src/pages/MapGame.tsx");
  const crosshair = elements(map).find(node => attribute(node, "className")?.split(/\s+/).includes("map-crosshair"));
  assert.ok(crosshair);
  const classes = attribute(crosshair, "className").split(/\s+/);
  for (const expected of ["h-7", "w-7", "flex", "items-center", "justify-center", "left-1/2", "top-1/2"]) assert.ok(classes.includes(expected));
  assert.match(crosshair.getText(map), /M12 5v14M5 12h14/);
});

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
  assert.ok(gridClasses.has("grid-cols-2"), "both columns may shrink without horizontal overflow");
  assert.ok(gridClasses.has("auto-rows-fr"), "both rows share available answer height");

  const options = [...html.matchAll(/<button\b[^>]*\baria-pressed="(?:true|false)"[^>]*>[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.equal(options.length, 4, "all four options are present at the same time");
  options.forEach((option, index) => {
    assert.ok(option.includes(escapeHtml(answerTexts[index])), `answer ${index + 1} keeps its complete text`);
    const classes = classesFrom(option);
    assert.ok(classes.has("min-h-20"), "answer buttons retain at least an 80px minimum height");
    assert.ok(classes.has("min-w-0"));
    assert.ok(option.includes("whitespace-normal"));
    assert.ok(option.includes("wrap-anywhere"));
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

async function sourceText(relativePath) {
  return readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");
}

function attribute(node, name) {
  const opening = ts.isJsxElement(node) ? node.openingElement : node;
  const value = opening.attributes?.properties.find(item => ts.isJsxAttribute(item) && item.name.text === name)?.initializer;
  return value && ts.isStringLiteral(value) ? value.text : undefined;
}

function elements(node) {
  return visit(node, item => ts.isJsxElement(item) || ts.isJsxSelfClosingElement(item));
}

function elementTag(node, tree) {
  return (ts.isJsxElement(node) ? node.openingElement : node).tagName.getText(tree);
}

function links(tree) {
  return elements(tree).filter(node => ["Link", "NavLink"].includes(elementTag(node, tree)));
}

test("navigation structure: the Today hub is not a separate screen", async () => {
  const header = await sourceTree("src/components/Header.tsx");
  const persistentGameLink = links(header).find(node => attribute(node, "to") === "/");
  assert.ok(persistentGameLink, "the persistent header starts the game flow");
  assert.ok(attribute(persistentGameLink, "aria-label"), "the icon-only header link has an accessible name");

  const start = await sourceText("src/pages/Start.tsx");
  assert.match(start, /next\?\.href\s*\?\?\s*["']\/wordle["']/, "the start route always chooses a playable game");
  assert.doesNotMatch(start, /next\?\.href\s*\?\?\s*["']\/scores["']/);

  const router = await sourceText("src/routes/AppRouter.tsx");
  assert.match(router, /path="\/today" element=\{<Navigate to="\/" replace \/>\}/);
  assert.doesNotMatch(router, /<Today\s*\/>/);

  for (const file of [
    "src/components/DailyJourney.tsx",
    "src/components/DailyQuiz.tsx",
    "src/pages/League.tsx",
    "src/pages/Leaderboard.tsx",
    "src/pages/Practice.tsx",
  ]) {
    const tree = await sourceTree(file);
    assert.equal(links(tree).filter(node => attribute(node, "to") === "/today").length, 0, `${file} does not link to the removed hub`);
  }
});

test("moderators can open player management without admin-only product data", async () => {
  const router = await sourceText("src/routes/AppRouter.tsx");
  const header = await sourceText("src/components/Header.tsx");
  const admin = await sourceText("src/pages/Admin.tsx");
  assert.match(router, /user\.role === "admin" \|\| user\.role === "mod"/, "moderators can reach the Players page");
  assert.match(header, /user\?\.role === "admin" \|\| user\?\.role === "mod"/, "moderators see its navigation button");
  assert.match(admin, /if \(isAdmin\) \{\s*void api\.adminProductReport\(\)/, "moderators do not request admin-only reports");
});

test("game screens have persistent previous and next game arrows", async () => {
  const router = await sourceText("src/routes/AppRouter.tsx");
  assert.match(router, /!reviewMode\s*&&\s*gameRoute\s*\?\s*<GameNavigation\s+navRef=\{navRef\}\s*\/>/);
  const navigation = await sourceText("src/components/GameNavigation.tsx");
  assert.match(navigation, /aria-label="Game navigation"/);
  assert.match(navigation, /aria-label=\{`Previous game:/);
  assert.match(navigation, /aria-label=\{`Next game:/);
  assert.match(navigation, /<ArrowLeft/);
  assert.match(navigation, /<ArrowRight/);
  assert.match(navigation, /fixed inset-x-0 bottom-0/);
  assert.match(navigation, /pathname === "\/map" \? "relative"/, "Map arrows sit after the controls instead of covering them");
  assert.match(navigation, /sameDestination = previous\.id === next\.id/, "one shared destination label replaces duplicate game names");
  const navCss = await sourceText("src/styles/index.css");
  assert.match(navCss, /\.game-navigation__link\s*\{[^}]*min-height: 2\.75rem/s, "arrow links retain a 44px touch target");
  assert.match(navCss, /\.game-navigation\s*\{[^}]*env\(safe-area-inset-bottom\)/s, "navigation still clears the iPhone home indicator");
  assert.match(router, /pathname === "\/map" \? "0px" : `\$\{navRef\.current\?\.getBoundingClientRect\(\)\.height/, "fixed bars reserve their measured height");
  assert.match(router, /observer\.observe\(navRef\.current\)/, "safe-area and size changes update the reserved space");
  assert.match(navigation, /item\.status !== "unavailable"/, "unavailable Map days do not lead to a dead game");
});

test("header Scores button opens a current-game dialog rather than navigating away", async () => {
  const header = await sourceText("src/components/Header.tsx");
  assert.match(header, /<ScoresDialog currentGame=/);
  assert.doesNotMatch(header, /to="\/scores"/);
  const scores = await sourceText("src/components/ScoresDialog.tsx");
  assert.match(scores, /aria-haspopup="dialog"/);
  assert.match(scores, /<DialogPortal/);
  assert.match(scores, /role="dialog"/);
  assert.match(scores, /setFilter\(currentGame \?\? "all"\)/);
  assert.match(scores, /api\.league\(\)/);
});

test("App frame gives the quiz board and score history the wide desktop shell", async () => {
  const tree = await sourceTree("src/routes/AppRouter.tsx");
  const wide = visit(tree, ts.isVariableDeclaration).find(node => node.name.getText(tree) === "wide");
  assert.ok(wide?.initializer, "the AppFrame wide-route allowlist exists");
  const routes = wide.initializer.getText(tree);
  assert.match(routes, /["']\/quiz["']/);
  assert.match(routes, /["']\/scores\/history["']/);
});

test("quiz board keeps six fixed, responsive choices after each answer", async () => {
  const tree = await sourceTree("src/pages/Quiz.tsx");
  const boardList = elements(tree).find(node => /cards\.map/.test(node.getText(tree)) && attribute(node, "className") === "quiz-choice-list");
  assert.ok(boardList, "all six questions are mapped into one continuous board");
  const cardButton = elements(tree).find(node => elementTag(node, tree) === "button" && node.getText(tree).includes("data-state="));
  assert.ok(cardButton);
  assert.match(cardButton.getText(tree), /data-state=/);
  assert.match(cardButton.getText(tree), /aria-pressed=/);
  assert.match(cardButton.getText(tree), /state !== "available"/, "played choices remain visible but cannot be picked again");

  const cards = Array.from({ length: 6 }, (_, index) => ({
    id: `card-${index + 1}`,
    subject: index % 2 ? "general" : "football",
    difficulty: "easy",
    points: 1,
    teaser: `Which event is question ${index + 1} about?`,
    source: "new",
    appearances: 1,
    selectedOrder: index < 2 ? index + 1 : null,
    answered: index === 0,
  }));
  const html = renderToStaticMarkup(createElement(QuizBoardGrid, { cards, busy: false, locked: true, onSelect: () => {} }));
  assert.equal((html.match(/<button\b/g) ?? []).length, 6, "answering does not remove a card");
  assert.match(html, /data-state="done"[^>]*aria-pressed="true"[^>]*disabled=""/);
  assert.match(html, /data-state="active"[^>]*aria-pressed="true"[^>]*disabled=""/);
  assert.equal((html.match(/data-state="available"/g) ?? []).length, 4);
  assert.match(html, /Pick 1 · Done/);
  assert.match(html, /Pick 2 · In play/);
  assert.match(html, /Choose/, "available questions invite the next choice");
  assert.match(html, /quiz-choice__points/, "points remain visible on each row");
  assert.match(html, /quiz-choice__status/, "played status remains visible after a choice");
  assert.match(html, /data-subject="football"/, "Football questions retain their accent");
  assert.match(html, /data-subject="general"/, "General Knowledge questions retain their accent");
  assert.match(html, /quiz-choice__number/, "questions have stable scan-friendly numbers");
  assert.doesNotMatch(html, /Back from yesterday|rollover/, "unused questions are not called out as rollover cards");
  const pressing = renderToStaticMarkup(createElement(QuizBoardGrid, { cards, busy: true, locked: false, pendingCardId: "card-3", onSelect: () => {} }));
  assert.match(pressing, /data-state="pressing"[^>]*aria-pressed="true"[^>]*disabled=""/, "a tapped card visibly presses before the server responds");
  assert.match(pressing, /Opening…/);
  assert.match(html, /quiz-choice-list/, "the raised card grid has been replaced by a question list");
  const css = await sourceText("src/styles/index.css");
  assert.match(css, /\.quiz-choice\[data-state="done"\][^}]*background: #e9f3ed/, "answered choices have a clear settled state");
  assert.match(css, /\.quiz-choice\s*\{[^}]*min-height: 4\.55rem/s, "phone rows are compact enough for the whole board");
  assert.match(css, /\.quiz-choice\s*\{[^}]*padding: 0\.2rem 0\.65rem/s, "phone rows leave room above fixed navigation");
  assert.doesNotMatch(css, /\.quiz-push-card/, "the previous raised-card styling is removed");
  assert.match(html, /Which event is question 1 about\?/, "Daily cards preview the question instead of repeating its subject");

  const practice = renderToStaticMarkup(createElement(QuizBoardGrid, { cards, mode: "practice", busy: false, locked: false, onSelect: () => {} }));
  assert.equal((practice.match(/<button\b/g) ?? []).length, 6, "Practice also keeps all six choices visible");
  assert.match(practice, /aria-label="Choose a practice question"/);
  assert.match(practice, /Choose/);
  assert.match(practice, /Pick 1 · Done/);
  assert.match(practice, /Which event is question 1 about\?/);

  const quizSource = await sourceText("src/pages/Quiz.tsx");
  assert.match(quizSource, /board && !activeCard && !reveal && board\.status !== "completed"/, "the six-card board is hidden while a question or result is shown");
  assert.match(quizSource, /ref=\{stageRef\}[\s\S]*?<QuizBoardGrid/, "the board is its own focused stage");
  assert.doesNotMatch(quizSource, /Pick four\. Make them count\.|Six cards, four picks/, "the quiz starts with a compact title instead of an explainer panel");

  const answers = elements(tree).find(node => attribute(node, "aria-label") === "Answer choices");
  assert.ok(answers, "answer choices form an accessible group");
  assert.equal(attribute(answers, "className"), "quiz-answer-grid");
  const answerButton = elements(answers).find(node => elementTag(node, tree) === "button");
  assert.ok(answerButton);
  const answerMarkup = answerButton.getText(tree);
  assert.match(answerMarkup, /className="quiz-answer saints-focus"/);
  assert.match(css, /\.quiz-answer\s*\{[^}]*overflow-wrap: anywhere/s, "full answer text remains readable");
});

test("Map opens on the game without a header strip or help row above the clue", async () => {
  const mapSource = await sourceText("src/pages/MapGame.tsx");
  const routes = await sourceText("src/routes/AppRouter.tsx");
  assert.match(mapSource, /<h1 className="sr-only">Map<\/h1>/);
  assert.doesNotMatch(mapSource, /<h1 className="text-xl[^>]*>Map<\/h1>/);
  assert.match(mapSource, /helpControl=\{<HelpButton title="How to play & map options" compact>/);
  assert.match(mapSource, /\{helpControl\}\s*<\/div>/, "help is in the map tool row, not above the clue");
  assert.match(routes, /path="\/map"[\s\S]*?<AppFrame compact>/, "Map uses the compact app frame");
  assert.doesNotMatch(mapSource, /MapGamePromo|Replay map introduction|<h1[^>]*>Pin the place/);
  assert.doesNotMatch(routes, /MapGamePromo|promoReviewMode/);
});

test("Practice quiz has no redundant Back to Daily button", async () => {
  const quizSource = await sourceText("src/pages/Quiz.tsx");
  assert.doesNotMatch(quizSource, /Back to Daily/);
  assert.match(quizSource, /\{value === "daily" \? "Daily" : "Practice"\}/);
});

test("large-print Wordle row controls retain visible high-contrast direction glyphs when disabled", async () => {
  const tree = await sourceTree("src/pages/Wordle.tsx");
  const previous = elements(tree).find(node => attribute(node, "aria-label") === "Show previous guess row");
  const next = elements(tree).find(node => attribute(node, "aria-label") === "Show next guess row");
  assert.ok(previous);
  assert.ok(next);
  assert.match(previous.getText(tree), /↑|&#8593;|&uarr;/, "the previous-row control has an unmistakable up glyph");
  assert.match(next.getText(tree), /↓|&#8595;|&darr;/, "the next-row control has an unmistakable down glyph");

  const declaration = visit(tree, ts.isVariableDeclaration).find(node => node.name.getText(tree) === "rowControlButtonClass");
  const classes = declaration?.initializer?.getText(tree) ?? "";
  assert.doesNotMatch(classes, /disabled:text-slate-(?:[0-4]00)/, "disabled arrows are not rendered in near-white slate");
  assert.match(classes, /disabled:text-slate-(?:[5-9]00|950)/, "disabled arrows preserve readable contrast");
});

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

test("Quiz choices stay tappable while the six-card board compacts on short phones", async () => {
  const css = await stylesheet();
  const shortPhoneRule = rulesFor(css, ".quiz-choice").find(rule =>
    rule.parent.type === "atrule" && rule.parent.name === "media"
    && rule.parent.params.includes("max-width: 759px")
    && rule.parent.params.includes("max-height: 720px")
  );
  assert.ok(shortPhoneRule);
  const rem = Number.parseFloat(values([shortPhoneRule], "min-height")[0]);
  assert.ok(rem >= 2.75, "a card keeps a touch-sized target");
  assert.ok(rem <= 4.15, "six cards can fit a short phone without clipping the mode switch");
});

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

test("Map fit calculation stays anchored when selected-pin review scrolls into view", async () => {
  const source = await readFile(new URL("../src/pages/MapGame.tsx", import.meta.url), "utf8");
  assert.match(source, /const sectionTop = sectionRect\.top \+ window\.scrollY;/);
  assert.match(source, /viewportHeight - sectionTop - navigationHeight - otherHeight/);
  assert.match(source, /draftSelection === null \? <div className="map-tools"/);
  assert.match(source, /aria-label="Change selected place"/);
});

test("Map tools keep readable labels on narrow phones", async () => {
  const source = await readFile(new URL("../src/pages/MapGame.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/index.css", import.meta.url), "utf8");
  assert.match(source, /map-tool__short-label">Pick centre/);
  assert.match(source, /map-tool__short-label">\{expanded \? "Shrink" : "Expand"\}/);
  assert.match(css, /@media \(max-width: 359px\)\s*\{[\s\S]*?\.map-tool \{ flex-direction: column;/);
  assert.match(css, /\.map-tool span \{ overflow-wrap: normal; white-space: nowrap; \}/);
});

test("tiny Map screens do not reserve hidden footer space", async () => {
  const router = await readFile(new URL("../src/routes/AppRouter.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/index.css", import.meta.url), "utf8");
  assert.match(router, /data-game=\{pathname === "\/map" \? "map" : undefined\}/);
  assert.match(css, /@media \(max-width: 359px\) and \(max-height: 650px\)\s*\{\s*\.app-main\[data-game="map"\]:not\(\[data-review="true"\]\) \{ padding-bottom: 0\.25rem; \}/);
});

function responsiveHeight(rule) {
  const value = values([rule], "height").at(-1);
  const match = value?.match(/(?:^|min\()clamp\(([\d.]+)px,\s*([\d.]+)[sd]?vh,\s*([\d.]+)px\)/);
  return match ? { minimum: Number(match[1]), viewport: Number(match[2]), maximum: Number(match[3]) } : null;
}

function assertMeaningfulExpansion(normal, expanded, viewport) {
  assert.ok(normal, `${viewport} default map height has bounded viewport-responsive sizing`);
  assert.ok(expanded, `${viewport} expanded map height has bounded viewport-responsive sizing`);
  assert.ok(expanded.minimum > normal.minimum, `${viewport} expansion increases the minimum height`);
  assert.ok(expanded.viewport > normal.viewport, `${viewport} expansion uses more of the viewport`);
  assert.ok(expanded.maximum > normal.maximum, `${viewport} expansion increases the maximum height`);
}

test("Map CSS structure: Larger map meaningfully expands mobile and desktop layouts", async () => {
  const css = await stylesheet();
  const normalRules = rulesFor(css, ".map-stage");
  const expandedRules = [];
  css.walkRules(rule => { if (/\[data-expanded\s*=\s*["']?true["']?\].*\.map-stage/.test(rule.selector)) expandedRules.push(rule); });
  const atViewport = (rule, query) => query
    ? rule.parent.type === "atrule" && rule.parent.params === query
    : rule.parent.type === "root";

  assertMeaningfulExpansion(
    responsiveHeight(normalRules.find(rule => atViewport(rule))),
    responsiveHeight(expandedRules.find(rule => atViewport(rule))),
    "mobile",
  );
  assert.match(values([normalRules.find(rule => atViewport(rule))], "height").at(-1), /--map-fit-height/);
  assertMeaningfulExpansion(
    responsiveHeight(normalRules.find(rule => atViewport(rule, "(min-width: 760px)"))),
    responsiveHeight(expandedRules.find(rule => atViewport(rule, "(min-width: 760px)"))),
    "desktop",
  );

  assert.ok(normalRules.flatMap(rule => values([rule], "height")).every(value => value !== "620px"), "the default desktop map is not locked to 620px");
  assert.match(values([normalRules.find(rule => atViewport(rule))], "max-height").at(-1), /100svh - var\(--app-header-height/, "mobile map height reserves room for clues and controls");
  assert.ok(expandedRules.flatMap(rule => values([rule], "min-height")).every(value => value !== "620px"), "expanded mode does not retain the hard 620px minimum that made the toggle a no-op");
});

test("score guide connector arrows reserve at least their own width", async () => {
  const tree = await sourceTree("src/pages/Leaderboard.tsx");
  const quizConnectorArrow = elements(tree).find(node => elementTag(node, tree) === "ArrowRight"
    && node.parent?.getText(tree).includes("min-h-29"));
  assert.ok(quizConnectorArrow, "the quiz score guide includes connector arrows");
  const wrapper = quizConnectorArrow.parent;
  assert.ok(wrapper && (ts.isJsxElement(wrapper) || ts.isJsxSelfClosingElement(wrapper)));
  const connectorClasses = attribute(wrapper, "className")?.split(/\s+/) ?? [];
  assert.ok(connectorClasses.includes("shrink-0"), "grid pressure cannot shrink the connector wrapper");
  assert.ok(connectorClasses.some(name => /^(?:min-)?w-(?:3\.5|4|5)$/.test(name)), "the wrapper is at least as wide as its 0.875rem arrow");

  const guideGrid = elements(tree).find(node => /QUIZ_JOURNEY\.map/.test(node.getText(tree)) && attribute(node, "className")?.includes("grid-cols-["));
  assert.ok(guideGrid);
  const fixedRemTracks = [...attribute(guideGrid, "className").matchAll(/_([\d.]+)rem(?=_|\])/g)].map(match => Number(match[1]));
  assert.ok(fixedRemTracks.every(width => width >= 0.875), "connector tracks are not narrower than the arrow");
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
