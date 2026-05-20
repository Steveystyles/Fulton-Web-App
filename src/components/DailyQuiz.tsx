import { ArrowRight, Check, CircleAlert, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { DailyQuizQuestion, QuizDifficulty } from "../lib/api";
import { Card } from "./Card";

type DailyQuizProps = {
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
  emptyMessage: string;
};

const difficultyClasses: Record<QuizDifficulty, string> = {
  easy: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  hard: "bg-red-50 text-saints-red ring-red-200",
};

function formatQuizDate(quizDate?: string) {
  if (!quizDate) {
    return "";
  }

  const [year, month, day] = quizDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(year, month - 1, day));
}

export function DailyQuiz({
  quizDate,
  questions,
  loading,
  error,
  emptyMessage,
}: DailyQuizProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState("");
  const [locked, setLocked] = useState(false);
  const [score, setScore] = useState(0);

  useEffect(() => {
    setCurrentIndex(0);
    setSelectedAnswer("");
    setLocked(false);
    setScore(0);
  }, [quizDate, questions]);

  const currentQuestion = questions[currentIndex];
  const isComplete = questions.length > 0 && currentIndex >= questions.length;
  const progressLabel = `${Math.min(currentIndex + 1, questions.length)} / ${questions.length}`;
  const formattedDate = formatQuizDate(quizDate);

  const answerState = useMemo(() => {
    if (!locked || currentQuestion === undefined) {
      return new Map<string, "neutral">();
    }

    return new Map(
      currentQuestion.answers.map((answer) => {
        if (answer === currentQuestion.correct_answer) {
          return [answer, "correct" as const];
        }
        if (answer === selectedAnswer) {
          return [answer, "incorrect" as const];
        }
        return [answer, "muted" as const];
      }),
    );
  }, [currentQuestion, locked, selectedAnswer]);

  function chooseAnswer(answer: string) {
    if (locked || currentQuestion === undefined) {
      return;
    }

    setSelectedAnswer(answer);
    setLocked(true);
    if (answer === currentQuestion.correct_answer) {
      setScore((currentScore) => currentScore + 1);
    }
  }

  function goNext() {
    setSelectedAnswer("");
    setLocked(false);
    setCurrentIndex((index) => index + 1);
  }

  function restart() {
    setCurrentIndex(0);
    setSelectedAnswer("");
    setLocked(false);
    setScore(0);
  }

  if (loading) {
    return (
      <Card>
        <div className="flex min-h-32 items-center justify-center gap-3 text-base font-black text-slate-600">
          <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin" />
          Loading today's quiz
        </div>
      </Card>
    );
  }

  if (error !== null) {
    return (
      <Card>
        <div className="flex items-start gap-3">
          <CircleAlert aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-saints-red" />
          <div>
            <p className="text-lg font-black text-slate-950">Quiz unavailable</p>
            <p className="mt-1 text-sm font-bold leading-relaxed text-slate-600">
              {error.message}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  if (questions.length === 0) {
    return (
      <Card>
        <p className="text-base font-bold leading-relaxed text-slate-600">{emptyMessage}</p>
      </Card>
    );
  }

  if (isComplete) {
    return (
      <Card>
        <div className="space-y-4 text-center">
          <div>
            <p className="text-sm font-black uppercase tracking-normal text-saints-red">
              {formattedDate}
            </p>
            <h3 className="mt-2 text-3xl font-black leading-none text-slate-950">
              Final score
            </h3>
            <p className="mt-3 text-5xl font-black leading-none text-saints-black">
              {score} / {questions.length}
            </p>
          </div>
          <button
            type="button"
            onClick={restart}
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-saints-red px-5 py-3 text-sm font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30"
          >
            <RotateCcw aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            Play again
          </button>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="space-y-4">
        <header className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-black uppercase tracking-normal text-saints-red">
              {formattedDate}
            </p>
            <p className="mt-1 text-sm font-bold text-slate-500">Question {progressLabel}</p>
          </div>
          <span
            className={[
              "shrink-0 rounded-full px-3 py-1 text-xs font-black uppercase ring-1",
              difficultyClasses[currentQuestion.difficulty],
            ].join(" ")}
          >
            {currentQuestion.difficulty}
          </span>
        </header>

        <h3 className="text-xl font-black leading-tight text-slate-950">
          {currentQuestion.question}
        </h3>

        <div className="grid gap-2" aria-label="Answer choices">
          {currentQuestion.answers.map((answer) => {
            const state = answerState.get(answer) ?? "neutral";
            const stateClass =
              state === "correct"
                ? "border-emerald-600 bg-emerald-600 text-white"
                : state === "incorrect"
                  ? "border-saints-red bg-saints-red text-white"
                  : state === "muted"
                    ? "border-slate-200 bg-slate-100 text-slate-500"
                    : "border-slate-200 bg-slate-50 text-slate-950 hover:border-saints-red/40 hover:bg-white";

            return (
              <button
                key={answer}
                type="button"
                onClick={() => chooseAnswer(answer)}
                disabled={locked}
                className={[
                  "flex min-h-14 items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-left text-base font-black transition focus:outline-none focus:ring-4 focus:ring-saints-red/20 disabled:cursor-default",
                  stateClass,
                ].join(" ")}
              >
                <span className="min-w-0">{answer}</span>
                {state === "correct" ? (
                  <Check aria-hidden="true" className="h-5 w-5 shrink-0" />
                ) : state === "incorrect" ? (
                  <X aria-hidden="true" className="h-5 w-5 shrink-0" />
                ) : null}
              </button>
            );
          })}
        </div>

        {locked ? (
          <div className="rounded-2xl bg-slate-50 p-3">
            <p className="text-base font-black text-slate-950">
              {selectedAnswer === currentQuestion.correct_answer ? "Correct" : "Not this time"}
            </p>
            <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-600">
              {currentQuestion.explanation}
            </p>
            <button
              type="button"
              onClick={goNext}
              className="mt-3 inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
            >
              {currentIndex === questions.length - 1 ? "See final score" : "Next question"}
              <ArrowRight aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
            </button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
