import { useEffect, useRef, useState } from "react";
import { Card } from "../components/Card";
import { DailyJourney, secondaryClass } from "../components/DailyJourney";
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
  return <div className="quiz-choice-list" role="group" aria-label={mode === "practice" ? "Choose a practice question" : "Choose a quiz question"}>
    {cards.map((card, index) => {
      const state = card.answered ? "done" : card.selectedOrder !== null ? "active" : pendingCardId === card.id ? "pressing" : "available";
      const status = card.answered ? `Pick ${card.selectedOrder} · Done` : state === "active" ? `Pick ${card.selectedOrder} · In play` : state === "pressing" ? "Opening…" : "Choose";
      return <button
        key={card.id}
        type="button"
        data-state={state}
        data-subject={card.subject}
        aria-pressed={state !== "available"}
        disabled={busy || locked || state !== "available"}
        onClick={() => onSelect(card.id)}
        className="quiz-choice saints-focus"
      >
        <span className="quiz-choice__number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
        <span className="quiz-choice__copy">
          <span className="quiz-choice__subject">{card.subject === "football" ? "Football" : "General knowledge"}</span>
          <strong className="quiz-choice__title">{card.difficulty}</strong>
          <span className="quiz-choice__topic">{card.teaser}</span>
        </span>
        <span className="quiz-choice__aside">
          <span className="quiz-choice__points" aria-label={`${card.points} ${card.points === 1 ? "point" : "points"}`}>{card.points} <small>{card.points === 1 ? "pt" : "pts"}</small></span>
          <span className="quiz-choice__status">{state === "done" ? <span aria-hidden="true">✓ </span> : null}{status}</span>
        </span>
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
    <section className="page-fade quiz-page" aria-label="Quiz">
      {!activeCard && !reveal && board?.status !== "completed" ? <div className="quiz-mode-switch mx-auto w-full max-w-3xl" role="group" aria-label="Quiz mode">
        {(["daily", "practice"] as Mode[]).map(value => (
          <button
            key={value}
            type="button"
            disabled={busy}
            onClick={() => setMode(value)}
            aria-pressed={mode === value}
            className="quiz-mode-switch__button saints-focus"
          >
            {value === "daily" ? "Daily" : "Practice"}
          </button>
        ))}
      </div> : null}

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

      {board && !activeCard && !reveal && board.status !== "completed" ? (
        <div ref={stageRef} tabIndex={-1} className="quiz-board mx-auto w-full max-w-3xl focus:outline-none">
          <div className="quiz-board__heading">
            <h1>{mode === "daily" ? "Quiz" : "Practice quiz"}</h1>
            <span aria-label={`${playedCount} of ${board.pickCount} questions answered`}>
              <strong>{playedCount}</strong> / {board.pickCount} played
            </span>
          </div>
          <QuizBoardGrid cards={board.cards} mode={mode} busy={busy} pendingCardId={pendingCardId} locked={false} onSelect={cardId => void selectCard(cardId)} />
          {!remainingCards.length ? (
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
          <div className="quiz-question-stage" data-mode={mode}>
            <div className="quiz-question-stage__progress" aria-label={`Question ${activeCard.selectedOrder} of ${board?.pickCount ?? 4}`}>
              {Array.from({ length: board?.pickCount ?? 4 }, (_, index) => (
                <span key={index} data-state={index + 1 < (activeCard.selectedOrder ?? 1) ? "done" : index + 1 === activeCard.selectedOrder ? "current" : "upcoming"} />
              ))}
            </div>
            <div className="quiz-question-stage__meta">
              <span>Question {activeCard.selectedOrder} of {board?.pickCount ?? 4}</span>
              <span>{activeCard.difficulty} · {activeCard.points} {activeCard.points === 1 ? "point" : "points"}</span>
            </div>
            <h1>{activeCard.question.question}</h1>
            <div
              className="quiz-answer-grid"
              role="group"
              aria-label="Answer choices"
            >
              {activeCard.question.answers.map((answerOption, index) => (
                <button
                  key={answerOption.id}
                  type="button"
                  aria-pressed={choice === answerOption.id}
                  disabled={busy}
                  onClick={() => setChoice(answerOption.id)}
                  className="quiz-answer saints-focus"
                >
                  <span className="quiz-answer__letter" aria-hidden="true">{String.fromCharCode(65 + index)}</span>
                  <span>{answerOption.text}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={!choice || busy}
              onClick={() => void answer()}
              className="quiz-submit saints-focus"
            >
              {busy ? "Checking…" : "Lock in answer"}
            </button>
          </div>
        </div>
      ) : null}

      {reveal ? (
        <div ref={stageRef} tabIndex={-1} className="mx-auto w-full max-w-2xl focus:outline-none">
          <div className="quiz-result-stage" data-correct={reveal.correct}>
            <p className="quiz-result-stage__label">
              {reveal.correct ? `Correct · +${reveal.pointsAwarded}` : "Not this time"}
            </p>
            {!reveal.correct ? <p className="quiz-result-stage__answer">Correct answer: {reveal.correctAnswer}</p> : null}
            <p className="quiz-result-stage__explanation">{reveal.explanation}</p>
            {reveal.interestingReason && reveal.interestingReason !== reveal.explanation ? (
              <p className="quiz-result-stage__fact"><strong>Did you know? </strong>{reveal.interestingReason}</p>
            ) : null}
            <button
              type="button"
              className="quiz-submit saints-focus"
              onClick={() => setReveal(null)}
            >
              {board?.status === "completed" ? "See final score" : "Back to the board"}
            </button>
          </div>
        </div>
      ) : null}

      {board?.status === "completed" && !reveal ? (
        <div ref={stageRef} tabIndex={-1} className="mx-auto w-full max-w-2xl focus:outline-none">
          <div className="quiz-result-stage">
            <p className="quiz-result-stage__label">Round complete</p>
            <h2 className="quiz-result-stage__score">{board.score} / {board.maxScore}</h2>
            <p className="quiz-result-stage__explanation">
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
              <p className="quiz-result-stage__fact">
                Practice only — your league score stays untouched.
              </p>
            )}
          </div>
        </div>
      ) : null}

    </section>
  );
}
