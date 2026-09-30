import { useEffect, useRef, useState } from "react";
import { Card } from "../components/Card";
import { DailyJourney, actionClass, secondaryClass } from "../components/DailyJourney";
import { GameFeedback } from "../components/GameFeedback";
import { api, type QuizBoard, type QuizCardAdjudication } from "../lib/api";

type Mode = "daily" | "practice";

export function QuizBoardGrid({ cards, busy, locked, onSelect }: {
  cards: QuizBoard["cards"];
  busy: boolean;
  locked: boolean;
  onSelect: (cardId: string) => void;
}) {
  return <div className="grid grid-cols-2 auto-rows-fr gap-2 min-[760px]:grid-cols-3" role="group" aria-label="Choose a quiz card">
    {cards.map(card => {
      const state = card.answered ? "done" : card.selectedOrder !== null ? "active" : "available";
      const status = card.answered ? `Pick ${card.selectedOrder} · Done` : state === "active" ? `Pick ${card.selectedOrder} · In play` : "Choose";
      const palette = state === "done"
        ? "border-saints-black bg-saints-black text-white shadow-inner"
        : state === "active"
          ? "border-saints-red bg-red-50 text-slate-950 ring-2 ring-saints-red/25"
          : card.source === "carry"
            ? "border-amber-300 bg-amber-50 text-slate-950 hover:border-amber-500"
            : "border-slate-200 bg-white text-slate-950 hover:border-saints-red";
      return <button
        key={card.id}
        type="button"
        data-state={state}
        aria-pressed={state !== "available"}
        disabled={busy || locked || state !== "available"}
        onClick={() => onSelect(card.id)}
        className={`saints-focus flex min-h-28 min-w-0 flex-col rounded-2xl border-2 p-3 text-left shadow-sm transition ${palette} ${state === "available" ? "active:scale-[0.98]" : "cursor-default"}`}
      >
        <span className="flex w-full flex-wrap items-start justify-between gap-1 text-[0.7rem] font-black uppercase tracking-wide">
          <span>{card.subject === "football" ? "Football" : "General"}</span>
          <span className={`rounded-full px-2 py-0.5 text-[0.65rem] ${state === "done" ? "bg-white/20 text-white" : state === "active" ? "bg-saints-red text-white" : "bg-slate-100 text-slate-700"}`}>{status}</span>
        </span>
        <strong className="mt-2 block text-base capitalize leading-tight">{card.difficulty} · {card.points} pts</strong>
        <span className={`mt-1 block text-xs leading-snug [overflow-wrap:anywhere] ${state === "done" ? "text-white/75" : "text-slate-600"}`}>{card.teaser}</span>
        {card.source === "carry" && state === "available" ? <span className="mt-auto pt-2 text-xs font-bold text-amber-800">Back from yesterday · {card.appearances}/7</span> : null}
      </button>;
    })}
  </div>;
}

export function Quiz() {
  const [mode, setMode] = useState<Mode>("daily");
  const [board, setBoard] = useState<QuizBoard | null>(null);
  const [choice, setChoice] = useState("");
  const [reveal, setReveal] = useState<QuizCardAdjudication | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadVersion, setLoadVersion] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setReveal(null); setBoard(null); setChoice("");
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
    setBusy(true); setError("");
    try { setBoard(await api.selectQuizCard(mode, cardId)); setChoice(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Card could not be selected."); }
    finally { setBusy(false); }
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
            className={`min-h-11 rounded-xl border text-sm font-black capitalize saints-focus ${mode === value ? "bg-saints-black text-white" : "bg-white"}`}
          >
            {value}
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
          <Card className="bg-saints-black text-white">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase text-white/60">
                  {mode === "daily" ? "Today's game-show board" : "Today's practice board"}
                </p>
                <h1 className="mt-1 text-2xl font-black">Choose your four</h1>
              </div>
              <span className="shrink-0 rounded-full bg-white/10 px-3 py-1 text-xs font-black">
                {playedCount} of {board.pickCount} done
              </span>
            </div>
            <p className="mt-2 text-sm text-white/75">
              Pick any {board.pickCount} of the six buttons. Answer one at a time; your picks stay marked Done.
            </p>
            <progress
              aria-label="Quiz cards played"
              value={playedCount}
              max={board.pickCount}
              className="mt-3 block h-1.5 w-full accent-red-600"
            />
          </Card>

          <QuizBoardGrid cards={board.cards} busy={busy} locked={Boolean(activeCard || reveal || board.status === "completed")} onSelect={cardId => void selectCard(cardId)} />
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
          <Card>
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
                  className={`min-h-16 min-w-0 whitespace-normal rounded-xl border p-3 text-left font-bold leading-snug [overflow-wrap:anywhere] saints-focus ${choice === answerOption.id ? "bg-saints-black text-white" : "bg-white"}`}
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
                Practice only — no league points or rollover changes.
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
