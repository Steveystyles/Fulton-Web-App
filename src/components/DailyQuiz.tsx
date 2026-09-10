import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DailyQuizQuestion, type DailyQuizResult, type DailyQuizSelection } from "../lib/api";
import { Card } from "./Card";
import { actionClass, secondaryClass, DailyJourney } from "./DailyJourney";

type Props = {
  category: "football" | "general"; storageScope: number; quizDate?: string;
  questions: DailyQuizQuestion[]; loading: boolean; error: Error | null;
  serverResult: DailyQuizResult | null; serverAnswers: DailyQuizSelection[]; onRefresh: () => void;
  practice?: boolean;
};
const difficultyPoints = { easy: 1, medium: 3, hard: 5 };

export function DailyQuiz({ category, storageScope, quizDate, questions, loading, error, serverResult, serverAnswers, onRefresh, practice = false }: Props) {
  const [answers, setAnswers] = useState(() => {
    if (practice || serverResult || serverAnswers.length) return serverAnswers;
    // Carry forward confirmed answers from the previous browser-only version.
    try {
      const legacy = JSON.parse(localStorage.getItem(`fultons:daily-quiz:v4:${storageScope}:${category}:${quizDate}`) ?? "null");
      if (!legacy || !Array.isArray(legacy.answers)) return serverAnswers;
      const count = Math.min(Math.max(0, Number(legacy.currentIndex) || 0), questions.length);
      const restored: DailyQuizSelection[] = [];
      for (let index = 0; index < count; index++) {
        if (!questions[index].answers.some(answer => answer.id === legacy.answers[index])) break;
        restored.push({ questionId: questions[index].id, choiceId: legacy.answers[index] });
      }
      return restored;
    } catch { return serverAnswers; }
  });
  const [result, setResult] = useState(serverResult);
  const [choice, setChoice] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const inFlight = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const committedKey = JSON.stringify(serverAnswers);
  useEffect(() => {
    // A slow visibility refresh must not roll back a newer confirmed answer.
    setAnswers(current => serverAnswers.length > current.length || serverAnswers.some((answer, index) =>
      answer.questionId !== current[index]?.questionId || answer.choiceId !== current[index]?.choiceId
    ) ? serverAnswers : current);
    if (serverResult) setResult(serverResult);
    setSaveError("");
  }, [committedKey, serverResult, quizDate, category]);
  const question = questions[answers.length];
  const draftKey = `fultons:quiz-draft:${practice ? "practice" : "daily"}:${storageScope}:${category}:${quizDate}:${question?.id}`;
  useEffect(() => {
    try {
      const stored = localStorage.getItem(draftKey);
      setChoice(question?.answers.some(answer => answer.id === stored) ? stored ?? "" : "");
    } catch { setChoice(""); }
  }, [draftKey]);
  function choose(value: string) {
    setChoice(value);
    try { localStorage.setItem(draftKey, value); } catch { /* The confirmed answer still saves on the server. */ }
  }
  async function next() {
    if (!quizDate || !question || !choice || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setSaveError("");
    try {
      const selections = [...answers, { questionId: question.id, choiceId: choice }];
      const response = practice
        ? (selections.length === questions.length ? { ...await api.submitPracticeQuiz({ date: quizDate, category, answers: selections }), answers: selections } : { answers: selections, result: undefined })
        : await api.saveQuizProgress({ date: quizDate, category, answers: selections });
      setAnswers(response.answers);
      if (response.result) setResult(response.result);
      setChoice("");
      try { localStorage.removeItem(draftKey); } catch { /* Optional draft cache. */ }
      requestAnimationFrame(() => heading.current?.focus());
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "Your answer could not be saved.");
    } finally { inFlight.current = false; setSaving(false); }
  }
  if (loading) return <Card><p role="status" className="p-4 text-center font-bold">Loading today's quiz…</p></Card>;
  if (error || !questions.length) return <Card><h2 className="font-black">Quiz not ready</h2><p className="mt-2 text-sm">{error?.message ?? "Today's questions are not available yet. Try another game while we get them ready."}</p><div className="mt-3 flex flex-wrap gap-2"><button className={secondaryClass} onClick={onRefresh}>Check again</button><Link className={actionClass} to="/">Choose another game</Link></div></Card>;
  if (result) return <Card>
    <p className="text-xs font-bold uppercase text-saints-red">{quizDate} · {category === "football" ? "Football" : "General knowledge"}</p>
    <h2 ref={heading} tabIndex={-1} className="mt-3 text-2xl font-black">{result.correctCount === questions.length ? "A perfect round!" : result.correctCount ? "A little more knowledge." : "A few discoveries for tomorrow."}</h2>
    <p className="mt-3 text-4xl font-black">{result.correctCount} of {questions.length} correct</p>
    <p className="mt-2 text-lg font-bold">{result.score} game points{result.bonusPoints ? ` · includes +${result.bonusPoints} perfect bonus` : ""}</p>
    <p className="mt-1 text-sm text-slate-500">{practice ? "Practice only · no league points or account records changed" : `${(result.maxScore ? result.score / result.maxScore * 10 : 0).toFixed(2)} league points · saved to your account`}</p>
    <div className="mt-5 space-y-3">{result.adjudications.map((answer, index) => {
      const original = questions.find(item => item.id === answer.questionId);
      const selected = original?.answers.find(item => item.id === answer.choiceId)?.text;
      return <details key={answer.questionId} open className={`rounded-xl border p-3 ${answer.correct ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
        <summary className="cursor-pointer font-black saints-focus">Question {index + 1} · {answer.correct ? "Correct" : "Not this time"} · {answer.pointsAwarded} pts</summary>
        <p className="mt-2 font-bold">{original?.question}</p>
        <p className="mt-2 text-sm">Your answer: {selected ?? answer.choiceId}</p>
        {!answer.correct ? <p className="mt-1 text-sm font-bold">Correct answer: {answer.correctAnswer}</p> : null}
        <p className="mt-2 text-sm leading-relaxed text-slate-700">{answer.explanation}</p>
      </details>;
    })}</div>
    {practice ? <div className="mt-4 flex flex-wrap gap-2"><button className={secondaryClass} onClick={() => { setAnswers([]); setResult(null); setChoice(""); }}>Try again</button><Link className={actionClass} to="/">Back to today's games</Link></div> : <DailyJourney current={category} summary={`Fulton's Quiz · ${quizDate}\n${category === "football" ? "Football" : "General knowledge"}: ${result.correctCount}/${questions.length} correct · ${result.score} game points`} />}
  </Card>;
  if (!question) return <Card><p>Your answers are ready to save.</p><button disabled={saving} className={`${secondaryClass} mt-3`} onClick={() => {
    if (!quizDate || inFlight.current) return;
    inFlight.current = true; setSaving(true); setSaveError("");
    void api.saveQuizProgress({ date: quizDate, category, answers }).then(response => { if (response.result) setResult(response.result); })
      .catch((reason: Error) => setSaveError(reason.message)).finally(() => { inFlight.current = false; setSaving(false); });
  }}>{saving ? "Saving…" : "Finish saving this round"}</button>{saveError ? <p role="alert" className="mt-2 text-sm text-saints-red">{saveError}</p> : null}</Card>;
  return <Card className="overflow-hidden p-0">
    <div className="bg-saints-black p-4 text-white"><p className="text-xs font-bold uppercase text-white/65">{quizDate} · {question.difficulty} · {difficultyPoints[question.difficulty]} points</p><h2 ref={heading} tabIndex={-1} className="mt-2 text-xl font-black">Question {answers.length + 1} of {questions.length}</h2><progress aria-label="Confirmed answers" value={answers.length} max={questions.length} className="mt-3 h-2 w-full accent-red-600" /></div>
    <div className="space-y-4 p-4">
      <p className="text-xl font-black leading-snug">{question.question}</p>
      <div className="grid gap-3" role="group" aria-label="Answer choices">{question.answers.map((answer, index) => <button key={answer.id} type="button" disabled={saving} aria-pressed={choice === answer.id} onClick={() => choose(answer.id)} className={`flex min-h-14 items-center gap-3 rounded-xl border p-3 text-left font-bold saints-focus disabled:opacity-60 ${choice === answer.id ? "border-saints-black bg-saints-black text-white" : "border-slate-300 bg-white"}`}><span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current">{String.fromCharCode(65 + index)}</span>{answer.text}</button>)}</div>
      <p className="text-sm text-slate-600">You can change your selection until you press {answers.length === questions.length - 1 ? "Finish round" : "Next question"}. {practice ? "Practice stays outside your daily scores." : "Confirmed answers are saved."} We'll reveal all three together.</p>
      <button type="button" disabled={!choice || saving} className={`${actionClass} w-full disabled:opacity-50`} onClick={() => void next()}>{saving ? "Saving your answer…" : answers.length === questions.length - 1 ? "Finish round" : "Next question"}</button>
      {saveError ? <div role="alert" className="rounded-xl bg-red-50 p-3 text-sm"><p>{saveError}</p><button className={`${secondaryClass} mt-2`} onClick={onRefresh}>Refresh saved progress</button></div> : null}
    </div>
  </Card>;
}
