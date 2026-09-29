import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { DailyJourney, actionClass, secondaryClass } from "../components/DailyJourney";
import { GameFeedback } from "../components/GameFeedback";
import { api, type QuizBoard, type QuizCardAdjudication } from "../lib/api";

type Mode = "daily" | "practice";

export function Quiz() {
  const [mode, setMode] = useState<Mode>("daily");
  const [board, setBoard] = useState<QuizBoard | null>(null);
  const [choice, setChoice] = useState("");
  const [reveal, setReveal] = useState<QuizCardAdjudication | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setReveal(null); setBoard(null);
    void api.quizBoard(mode).then(value => { if (active) setBoard(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Quiz board failed to load."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode]);

  const activeCard = board?.cards.find(card => card.selectedOrder !== null && !card.answered);

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

  return <section className="page-fade space-y-3" aria-label="Quiz">
    <div className="grid grid-cols-2 gap-2" role="group" aria-label="Quiz mode">
      {(["daily", "practice"] as Mode[]).map(value => <button key={value} type="button" onClick={() => setMode(value)} aria-pressed={mode === value} className={`min-h-11 rounded-xl border text-sm font-black capitalize saints-focus ${mode === value ? "bg-saints-black text-white" : "bg-white"}`}>{value}</button>)}
    </div>
    {loading ? <Card><p role="status">Building your board…</p></Card> : null}
    {error ? <Card><p role="alert" className="text-saints-red">{error}</p></Card> : null}
    {board && !activeCard && !reveal && board.status !== "completed" ? <>
      <Card className="bg-saints-black text-white"><p className="text-xs font-bold uppercase text-white/60">{mode === "daily" ? "Today's game-show board" : "Today's practice board"}</p><h1 className="mt-2 text-2xl font-black">Pick {board.pickCount - board.selectedCount} more</h1><p className="mt-2 text-sm text-white/75">Choose by subject and stakes. The question stays hidden until you commit.</p></Card>
      <div className="grid grid-cols-2 gap-3">{board.cards.map(card => <button key={card.id} type="button" disabled={busy || card.selectedOrder !== null} onClick={() => void selectCard(card.id)} className={`min-h-32 rounded-2xl border p-3 text-left shadow-sm saints-focus disabled:opacity-55 ${card.source === "carry" ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}>
        <span className="text-xs font-black uppercase text-saints-red">{card.subject === "football" ? "Football" : "General"}</span>
        <strong className="mt-2 block text-lg capitalize">{card.difficulty} · {card.points} pts</strong>
        <span className="mt-2 block text-xs text-slate-600">{card.teaser}</span>
        {card.source === "carry" ? <span className="mt-2 block text-xs font-bold text-amber-800">Back from yesterday · {card.appearances}/7</span> : null}
        {card.answered ? <span className="mt-2 block text-xs font-black text-emerald-700">Played</span> : null}
      </button>)}</div>
    </> : null}
    {activeCard?.question && !reveal ? <Card>
      <p className="text-xs font-black uppercase text-saints-red">Pick {activeCard.selectedOrder} of 4 · {activeCard.difficulty} · {activeCard.points} pts</p>
      <h1 className="mt-3 text-xl font-black">{activeCard.question.question}</h1>
      <div className="mt-4 grid grid-cols-2 gap-2">{activeCard.question.answers.map(answerOption => <button key={answerOption.id} type="button" aria-pressed={choice === answerOption.id} onClick={() => setChoice(answerOption.id)} className={`min-h-20 rounded-xl border p-3 text-left font-bold saints-focus ${choice === answerOption.id ? "bg-saints-black text-white" : "bg-white"}`}>{answerOption.text}</button>)}</div>
      <button type="button" disabled={!choice || busy} onClick={() => void answer()} className={`${actionClass} mt-4 w-full disabled:opacity-50`}>{busy ? "Checking…" : "Lock in answer"}</button>
    </Card> : null}
    {reveal ? <Card className={reveal.correct ? "border-emerald-300 bg-emerald-50" : "border-amber-300 bg-amber-50"}>
      <p className="text-sm font-black uppercase">{reveal.correct ? `Correct · +${reveal.pointsAwarded}` : "Not this time"}</p>
      {!reveal.correct ? <p className="mt-2 font-black">Correct answer: {reveal.correctAnswer}</p> : null}
      <p className="mt-2 text-sm leading-relaxed">{reveal.explanation}</p>
      {reveal.interestingReason && reveal.interestingReason !== reveal.explanation ? <p className="mt-2 text-sm"><strong>Did you know? </strong>{reveal.interestingReason}</p> : null}
      <button type="button" className={`${actionClass} mt-4 w-full`} onClick={() => setReveal(null)}>{board?.status === "completed" ? "See final score" : "Back to the board"}</button>
    </Card> : null}
    {board?.status === "completed" && !reveal ? <Card>
      <p className="text-xs font-black uppercase text-saints-red">Round complete</p><h2 className="mt-2 text-3xl font-black">{board.score} / {board.maxScore}</h2><p className="mt-2">{board.correctCount} of 4 correct{board.bonusPoints ? ` · +${board.bonusPoints} perfect bonus` : ""}</p>
      {mode === "daily" ? <><GameFeedback game="quiz" /><DailyJourney current="quiz" summary={`Fulton's Quiz · ${board.date}\nQuiz: ${board.score}/${board.maxScore}`} /></> : <p className="mt-3 text-sm text-slate-600">Practice only — no league points or rollover changes.</p>}
    </Card> : null}
    {mode === "practice" ? <button type="button" className={secondaryClass} onClick={() => setMode("daily")}>Back to Daily</button> : null}
  </section>;
}
