import { useEffect, useRef, useState } from "react";
import { Card } from "../components/Card";
import { DailyJourney, actionClass, secondaryClass } from "../components/DailyJourney";
import { GameFeedback } from "../components/GameFeedback";
import { api, type QuizBoard, type QuizCardAdjudication } from "../lib/api";

type Mode = "daily" | "practice";

export function QuizBoardGrid({ cards, mode = "daily", busy, locked, pendingCardId, onSelect }: {
  cards: QuizBoard["cards"];
  mode?: Mode;
  busy: boolean;
  locked: boolean;
  pendingCardId?: string | null;
  onSelect: (cardId: string) => void;
}) {
  const renderCard = (card: QuizBoard["cards"][number]) => {
      const state = card.answered ? "done" : card.selectedOrder !== null ? "active" : pendingCardId === card.id ? "pressing" : "available";
      const status = card.answered ? `Pick ${card.selectedOrder} · Done` : state === "active" ? `Pick ${card.selectedOrder} · In play` : state === "pressing" ? "Opening…" : mode === "practice" ? "Play this" : "Pick me";
      return <button
        key={card.id}
        type="button"
        data-state={state}
        data-subject={card.subject}
        aria-pressed={state !== "available"}
        disabled={busy || locked || state !== "available"}
        onClick={() => onSelect(card.id)}
        className={`quiz-push-card saints-focus flex min-h-40 min-w-0 flex-col rounded-2xl border-2 p-3 text-left text-slate-950 ${state === "available" ? "cursor-pointer" : "cursor-default"}`}
      >
        <span className="flex w-full items-start justify-between gap-2">
          <span className="quiz-push-card__subject text-[0.7rem] font-black uppercase tracking-wider">{card.subject === "football" ? "Football" : "General"}</span>
          <span className="quiz-push-card__points" aria-label={`${card.points} ${card.points === 1 ? "point" : "points"}`}>{card.points} <span aria-hidden="true">{card.points === 1 ? "pt" : "pts"}</span></span>
        </span>
        <strong className="mt-3 block text-xl capitalize leading-tight">{card.difficulty}</strong>
        <span className="mt-1 block text-xs leading-snug text-slate-600 [overflow-wrap:anywhere]">{card.teaser.replace(/^(Football|General knowledge) · /, "")}</span>
        <span className="quiz-push-card__action mt-auto flex w-full items-center justify-between gap-1 pt-3 text-xs font-black">
          <span>{status}</span>
          <span aria-hidden="true" className="quiz-push-card__indicator">{state === "available" ? "↓" : "✓"}</span>
        </span>
      </button>;
  };

  if (mode === "practice") {
    return <div className="space-y-4" aria-label="Practice quiz choices">
      {([
        { subject: "football", title: "Football", hint: "A little club knowledge" },
        { subject: "general", title: "General knowledge", hint: "Something beyond the pitch" },
      ] as const).map(group => {
        const groupCards = cards.filter(card => card.subject === group.subject);
        if (!groupCards.length) return null;
        return <section key={group.subject} aria-label={`${group.title} practice cards`} className="space-y-2">
          <div className="flex items-end justify-between gap-2 px-1">
            <div>
              <h2 className="text-lg font-black text-slate-950">{group.title}</h2>
              <p className="text-xs font-medium text-slate-600">{group.hint}</p>
            </div>
            <span className="text-xs font-bold text-slate-500">{groupCards.length} {groupCards.length === 1 ? "card" : "cards"}</span>
          </div>
          <div className="grid grid-cols-2 auto-rows-fr gap-2 min-[760px]:grid-cols-3" role="group" aria-label={`Choose a ${group.title} practice card`}>
            {groupCards.map(renderCard)}
          </div>
        </section>;
      })}
    </div>;
  }

  return <div className="grid grid-cols-2 auto-rows-fr gap-2 min-[760px]:grid-cols-3" role="group" aria-label="Choose a quiz card">
    {cards.map(renderCard)}
  </div>;
}

export function Quiz() {
  const [mode, setMode] = useState<Mode>("daily");
  const [board, setBoard] = useState<QuizBoard | null>(null);
  const [choice, setChoice] = useState("");
  const [reveal, setReveal] = useState<QuizCardAdjudication | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingCardId, setPendingCardId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loadVersion, setLoadVersion] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setReveal(null); setBoard(null); setChoice(""); setPendingCardId(null);
    void api.quizBoard(mode).then(value => { if (active) setBoard(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Quiz board failed to load."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loadVersion, mode]);

  const activeCard = board?.cards.find(card => card.selectedOrder !== null && !card.answered);
  const remainingCards = board?.cards.filter(card => card.selectedOrder === null) ?? [];
  const playedCount = board?.cards.filter(card => card.answered).length ?? 0;
  const stageKey = activeCard
    ? `question:${activeCard.id}`
    : reveal
      ? `reveal:${reveal.cardId}`
      : board?.status === "completed"
        ? "complete"
        : board
          ? `board:${playedCount}`
          : "";

  useEffect(() => {
    if (!stageKey) return;
    const animationFrame = window.requestAnimationFrame(() => {
      stageRef.current?.focus({ preventScroll: true });
      stageRef.current?.scrollIntoView({ block: "start" });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [stageKey]);

  async function selectCard(cardId: string) {
    if (busy || activeCard) return;
    setBusy(true); setPendingCardId(cardId); setError("");
    try { setBoard(await api.selectQuizCard(mode, cardId)); setChoice(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Card could not be selected."); }
    finally { setBusy(false); setPendingCardId(null); }
  }

  async function answer() {
    if (!activeCard || !choice || busy) return;
    setBusy(true); setError("");
    try {
      const response = await api.answerQuizCard(mode, activeCard.id, choice);
      setBoard(response.board); setReveal(response.adjudication); setChoice("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Answer could not be saved."); }
    finally { setBusy(false); }
  }

  return (
    <section className="page-fade space-y-3" aria-label="Quiz">
      <div className="mx-auto grid w-full max-w-md grid-cols-2 gap-2" role="group" aria-label="Quiz mode">
        {(["daily", "practice"] as Mode[]).map(value => (
          <button
            key={value}
            type="button"
            disabled={busy}
            onClick={() => setMode(value)}
            aria-pressed={mode === value}
            className={`min-h-14 rounded-xl border px-2 py-2 text-center saints-focus ${mode === value ? value === "practice" ? "border-amber-300 bg-amber-100 text-amber-950 shadow-sm" : "border-saints-black bg-saints-black text-white" : "border-slate-200 bg-white text-slate-700"}`}
          >
            <span className="block text-sm font-black capitalize">{value}</span>
            <span className={`block text-[0.68rem] font-semibold ${mode === "daily" && value === "daily" ? "text-white/75" : "opacity-70"}`}>{value === "daily" ? "League game" : "Just for fun"}</span>
          </button>
        ))}
      </div>

      {loading ? <Card className="mx-auto max-w-2xl"><p role="status">Building your board…</p></Card> : null}
      {error ? (
        <Card className="mx-auto max-w-2xl">
          <p role="alert" className="text-saints-red">{error}</p>
          {!board ? (
            <button
              type="button"
              className={`${secondaryClass} mt-3`}
              onClick={() => setLoadVersion(value => value + 1)}
            >
              Try loading the board again
            </button>
          ) : null}
        </Card>
      ) : null}

      {board ? (
        <div ref={!activeCard && !reveal && board.status !== "completed" ? stageRef : undefined} tabIndex={-1} className="mx-auto w-full max-w-3xl space-y-3 focus:outline-none">
          {mode === "daily" ? <Card className="relative isolate border border-red-800 bg-gradient-to-br from-saints-red via-red-700 to-saints-black text-white shadow-lg">
            <div aria-hidden="true" className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full border-[20px] border-white/10" />
            <div className="relative">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-black uppercase tracking-widest text-white/75">Today&apos;s quiz</p>
                  <h1 className="mt-2 text-2xl font-black leading-tight">{board.status === "completed" ? "Your four picks" : "Pick four. Make them count."}</h1>
                </div>
                <span className="shrink-0 rounded-full border border-white/30 bg-white/15 px-3 py-1 text-xs font-black">
                  {playedCount}/{board.pickCount} played
                </span>
              </div>
              <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/90">Six cards, four picks. Mix Football and General Knowledge however you like. Each answer brings you closer to your final score.</p>
              <progress aria-label="Quiz cards played" value={playedCount} max={board.pickCount} className="sr-only" />
              <div className="mt-4 grid gap-2" style={{ gridTemplateColumns: `repeat(${board.pickCount}, minmax(0, 1fr))` }} aria-hidden="true">
                {Array.from({ length: board.pickCount }, (_, index) => <span key={index} className={`h-2 rounded-full ${index < playedCount ? "bg-white" : "bg-white/30"}`} />)}
              </div>
            </div>
          </Card> : <Card className="border border-amber-200 bg-gradient-to-br from-amber-50 via-orange-50 to-white text-slate-950">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase text-amber-800">A no-pressure run</p>
                <h1 className="mt-1 text-2xl font-black">Take your pick</h1>
              </div>
              <span className="shrink-0 rounded-full bg-white px-3 py-1 text-xs font-black text-amber-900">
                {playedCount} of {board.pickCount} done
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-700">
              Choose {board.pickCount} of the six cards. Try Football, General Knowledge, or a mix. Your picks stay here when done.
            </p>
            <p className="mt-2 text-xs font-bold text-amber-900">No pressure — your league score stays untouched.</p>
            <progress
              aria-label="Quiz cards played"
              value={playedCount}
              max={board.pickCount}
              className="mt-3 block h-1.5 w-full accent-red-600"
            />
          </Card>}

          <QuizBoardGrid cards={board.cards} mode={mode} busy={busy} pendingCardId={pendingCardId} locked={Boolean(activeCard || reveal || board.status === "completed")} onSelect={cardId => void selectCard(cardId)} />
          {!remainingCards.length && !activeCard && !reveal && board.status !== "completed" ? (
            <Card>
              <p role="alert">No playable cards are available. Reload the board to continue.</p>
              <button
                type="button"
                className={`${secondaryClass} mt-3`}
                onClick={() => setLoadVersion(value => value + 1)}
              >
                Reload board
              </button>
            </Card>
          ) : null}
        </div>
      ) : null}

      {activeCard?.question && !reveal ? (
        <div ref={stageRef} tabIndex={-1} className="mx-auto w-full max-w-2xl focus:outline-none">
          <Card className={mode === "daily" ? "border border-rose-200 bg-gradient-to-b from-white to-rose-50/60" : ""}>
            <p className="text-xs font-black uppercase text-saints-red">
              Pick {activeCard.selectedOrder} of {board?.pickCount ?? 4} · {activeCard.difficulty} · {activeCard.points} pts
            </p>
            <h1 className="mt-3 text-xl font-black [overflow-wrap:anywhere]">{activeCard.question.question}</h1>
            <div
              className="mt-4 grid min-w-0 grid-cols-[repeat(2,minmax(0,1fr))] auto-rows-fr gap-2"
              role="group"
              aria-label="Answer choices"
            >
              {activeCard.question.answers.map(answerOption => (
                <button
                  key={answerOption.id}
                  type="button"
                  aria-pressed={choice === answerOption.id}
                  disabled={busy}
                  onClick={() => setChoice(answerOption.id)}
                  className={`min-h-16 min-w-0 whitespace-normal rounded-xl border p-3 text-left font-bold leading-snug [overflow-wrap:anywhere] saints-focus ${choice === answerOption.id ? mode === "daily" ? "border-saints-red bg-saints-red text-white" : "bg-saints-black text-white" : "border-slate-200 bg-white hover:border-saints-red"}`}
                >
                  {answerOption.text}
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={!choice || busy}
              onClick={() => void answer()}
              className={`${actionClass} mt-4 w-full disabled:opacity-50`}
            >
              {busy ? "Checking…" : "Lock in answer"}
            </button>
          </Card>
        </div>
      ) : null}

      {reveal ? (
        <div ref={stageRef} tabIndex={-1} className="mx-auto w-full max-w-2xl focus:outline-none">
          <Card className={reveal.correct ? "border-emerald-300 bg-emerald-50" : "border-amber-300 bg-amber-50"}>
            <p className="text-sm font-black uppercase">
              {reveal.correct ? `Correct · +${reveal.pointsAwarded}` : "Not this time"}
            </p>
            {!reveal.correct ? <p className="mt-2 font-black">Correct answer: {reveal.correctAnswer}</p> : null}
            <p className="mt-2 text-sm leading-relaxed">{reveal.explanation}</p>
            {reveal.interestingReason && reveal.interestingReason !== reveal.explanation ? (
              <p className="mt-2 text-sm"><strong>Did you know? </strong>{reveal.interestingReason}</p>
            ) : null}
            <button
              type="button"
              className={`${actionClass} mt-4 w-full`}
              onClick={() => setReveal(null)}
            >
              {board?.status === "completed" ? "See final score" : "Back to the board"}
            </button>
          </Card>
        </div>
      ) : null}

      {board?.status === "completed" && !reveal ? (
        <div ref={stageRef} tabIndex={-1} className="mx-auto w-full max-w-2xl focus:outline-none">
          <Card>
            <p className="text-xs font-black uppercase text-saints-red">Round complete</p>
            <h2 className="mt-2 text-3xl font-black">{board.score} / {board.maxScore}</h2>
            <p className="mt-2">
              {board.correctCount} of {board.pickCount} correct
              {board.bonusPoints ? ` · +${board.bonusPoints} perfect bonus` : ""}
            </p>
            {mode === "daily" ? (
              <>
                <GameFeedback game="quiz" />
                <DailyJourney
                  current="quiz"
                  summary={`Fulton's Quiz · ${board.date}\nQuiz: ${board.score}/${board.maxScore}`}
                />
              </>
            ) : (
              <p className="mt-3 text-sm text-slate-600">
                Practice only — your league score stays untouched.
              </p>
            )}
          </Card>
        </div>
      ) : null}

      {mode === "practice" ? (
        <button type="button" disabled={busy} className={secondaryClass} onClick={() => setMode("daily")}>
          Back to Daily
        </button>
      ) : null}
    </section>
  );
}
