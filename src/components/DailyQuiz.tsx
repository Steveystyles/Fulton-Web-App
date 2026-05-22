import { ArrowRight, Check, CircleAlert, LoaderCircle, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type DailyQuizQuestion, type DailyQuizResult, type QuizDifficulty } from "../lib/api";
import { Card } from "./Card";

type DailyQuizProps = {
  quizId: "football" | "general";
  storageScope: string | number;
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
  emptyMessage: string;
};

type StoredQuizState = {
  version: number;
  currentIndex: number;
  answers: string[];
};

type QuizRuntimeState = StoredQuizState & {
  storageKey: string;
};

const storageVersion = 2;
const emptyRuntimeState: QuizRuntimeState = {
  storageKey: "",
  version: storageVersion,
  currentIndex: 0,
  answers: [],
};

const difficultyClasses: Record<QuizDifficulty, string> = {
  easy: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  hard: "bg-saints-redSoft text-saints-red ring-red-200",
};
const difficultyPoints: Record<QuizDifficulty, number> = {
  easy: 1,
  medium: 3,
  hard: 5,
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

function quizStorageKey(
  quizId: DailyQuizProps["quizId"],
  storageScope: DailyQuizProps["storageScope"],
  quizDate: string,
) {
  return `fultons:daily-quiz:${storageScope}:${quizId}:${quizDate}`;
}

function normaliseStoredState(value: unknown, questionCount: number): StoredQuizState {
  if (value === null || typeof value !== "object") {
    return { version: storageVersion, currentIndex: 0, answers: [] };
  }

  const payload = value as Partial<StoredQuizState>;
  if (payload.version !== storageVersion) {
    return { version: storageVersion, currentIndex: 0, answers: [] };
  }
  const answers = Array.isArray(payload.answers)
    ? payload.answers
        .filter((answer): answer is string => typeof answer === "string")
        .slice(0, questionCount)
    : [];
  const rawIndex = Number(payload.currentIndex ?? 0);
  const currentIndex = Number.isFinite(rawIndex)
    ? Math.max(0, Math.min(questionCount, Math.floor(rawIndex)))
    : 0;

  return {
    version: storageVersion,
    currentIndex: Math.min(currentIndex, answers.length === questionCount ? questionCount : answers.length),
    answers,
  };
}

function readStoredQuizState(storageKey: string, questionCount: number): StoredQuizState {
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    return normaliseStoredState(rawValue ? JSON.parse(rawValue) : null, questionCount);
  } catch {
    return { version: storageVersion, currentIndex: 0, answers: [] };
  }
}

function writeStoredQuizState(storageKey: string, state: StoredQuizState) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    // Ignore storage failures; the in-memory quiz state still works.
  }
}

export function DailyQuiz({
  quizId,
  storageScope,
  quizDate,
  questions,
  loading,
  error,
  emptyMessage,
}: DailyQuizProps) {
  const [quizState, setQuizState] = useState<QuizRuntimeState>(emptyRuntimeState);
  const [savedResult, setSavedResult] = useState<DailyQuizResult | null>(null);
  const [scoreError, setScoreError] = useState("");
  const storageKey = useMemo(() => {
    return quizDate && questions.length > 0
      ? quizStorageKey(quizId, storageScope, quizDate)
      : "";
  }, [quizDate, questions.length, quizId, storageScope]);

  useEffect(() => {
    if (!storageKey) {
      setQuizState(emptyRuntimeState);
      return;
    }

    const restoredState = readStoredQuizState(storageKey, questions.length);
    setQuizState({ ...restoredState, storageKey });
  }, [questions.length, storageKey]);

  useEffect(() => {
    setSavedResult(null);
    setScoreError("");
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || quizState.storageKey !== storageKey || questions.length === 0) {
      return;
    }

    writeStoredQuizState(storageKey, {
      version: storageVersion,
      currentIndex: quizState.currentIndex,
      answers: quizState.answers.slice(0, questions.length),
    });
  }, [questions.length, quizState, storageKey]);

  const answers = quizState.storageKey === storageKey ? quizState.answers : [];
  const currentIndex =
    quizState.storageKey === storageKey
      ? Math.min(quizState.currentIndex, questions.length)
      : 0;
  const currentQuestion = questions[currentIndex];
  const currentAnswer = currentQuestion === undefined ? "" : answers[currentIndex] ?? "";
  const locked = currentAnswer !== "";
  const isComplete = questions.length > 0 && currentIndex >= questions.length;
  const progressLabel = `${Math.min(currentIndex + 1, questions.length)} / ${questions.length}`;
  const formattedDate = formatQuizDate(quizDate);
  const score = useMemo(() => {
    return questions.reduce((total, question, index) => {
      return total + (answers[index] === question.correct_answer ? difficultyPoints[question.difficulty] : 0);
    }, 0);
  }, [answers, questions]);
  const maxScore = useMemo(() => {
    return questions.reduce((total, question) => total + difficultyPoints[question.difficulty], 0);
  }, [questions]);

  useEffect(() => {
    let active = true;

    if (
      !isComplete ||
      !quizDate ||
      savedResult !== null ||
      answers.length !== questions.length
    ) {
      return;
    }
    const resultDate = quizDate;

    async function saveScore() {
      try {
        const response = await api.submitDailyQuizResult({
          date: resultDate,
          category: quizId,
          answers,
        });
        if (active) {
          setSavedResult(response.result);
          setScoreError("");
        }
      } catch (caughtError) {
        if (active) {
          setScoreError(caughtError instanceof Error ? caughtError.message : "Score was not saved.");
        }
      }
    }

    void saveScore();

    return () => {
      active = false;
    };
  }, [answers, isComplete, questions.length, quizDate, quizId, savedResult]);

  const answerState = useMemo(() => {
    if (!locked || currentQuestion === undefined) {
      return new Map<string, "neutral">();
    }

    return new Map(
      currentQuestion.answers.map((answer) => {
        if (answer === currentQuestion.correct_answer) {
          return [answer, "correct" as const];
        }
        if (answer === currentAnswer) {
          return [answer, "incorrect" as const];
        }
        return [answer, "muted" as const];
      }),
    );
  }, [currentAnswer, currentQuestion, locked]);

  function chooseAnswer(answer: string) {
    if (locked || currentQuestion === undefined || !storageKey) {
      return;
    }

    setQuizState((currentState) => {
      const baseState =
        currentState.storageKey === storageKey
          ? currentState
          : { ...emptyRuntimeState, storageKey };
      const nextAnswers = baseState.answers.slice(0, questions.length);
      nextAnswers[currentIndex] = answer;
      return {
        ...baseState,
        currentIndex,
        answers: nextAnswers,
      };
    });
  }

  function goNext() {
    setQuizState((currentState) => {
      const baseState =
        currentState.storageKey === storageKey
          ? currentState
          : { ...emptyRuntimeState, storageKey };
      return {
        ...baseState,
        currentIndex: Math.min(currentIndex + 1, questions.length),
      };
    });
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
      <div className="space-y-3">
        <Card>
          <div className="space-y-3 text-center">
            <div>
              <p className="text-sm font-black uppercase tracking-normal text-saints-red">
                {formattedDate}
              </p>
              <h3 className="mt-2 text-3xl font-black leading-none text-slate-950">
                Final score
              </h3>
              <p className="mt-3 text-5xl font-black leading-none text-saints-black">
                {savedResult?.score ?? score} / {savedResult?.maxScore ?? maxScore}
              </p>
            </div>
            <p className="text-sm font-semibold leading-relaxed text-slate-600">
              Easy questions are worth 1, medium 3, and hard 5. A fresh quiz will unlock after the daily refresh.
            </p>
            {scoreError ? (
              <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
                {scoreError}
              </p>
            ) : null}
          </div>
        </Card>

        <section className="space-y-3" aria-label="Completed quiz answer summary">
          {questions.map((question, index) => {
            const userAnswer = answers[index] ?? "No answer";
            const isCorrect = userAnswer === question.correct_answer;

            return (
              <Card key={`${question.question}-${index}`} className="p-4">
                <div className="flex items-start gap-3">
                  <span
                    className={[
                      "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white",
                      isCorrect ? "bg-emerald-600" : "bg-saints-red",
                    ].join(" ")}
                  >
                    {isCorrect ? (
                      <Check aria-hidden="true" className="h-4 w-4" strokeWidth={2.6} />
                    ) : (
                      <X aria-hidden="true" className="h-4 w-4" strokeWidth={2.6} />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-black uppercase tracking-normal text-saints-red">
                      Question {index + 1} / {difficultyPoints[question.difficulty]} pts
                    </p>
                    <h3 className="mt-1 text-base font-black leading-tight text-slate-950">
                      {question.question}
                    </h3>
                  </div>
                </div>

                <div className="mt-3 grid gap-2">
                  <div className="rounded-2xl bg-slate-50 p-3">
                    <p className="text-xs font-black uppercase tracking-normal text-slate-500">
                      Your answer
                    </p>
                    <p className="mt-1 text-sm font-black text-slate-950">{userAnswer}</p>
                  </div>
                  <div className="rounded-2xl bg-emerald-50 p-3">
                    <p className="text-xs font-black uppercase tracking-normal text-emerald-700">
                      Correct answer
                    </p>
                    <p className="mt-1 text-sm font-black text-slate-950">
                      {question.correct_answer}
                    </p>
                  </div>
                </div>

                <p className="mt-3 text-sm font-semibold leading-relaxed text-slate-600">
                  {question.explanation}
                </p>
              </Card>
            );
          })}
        </section>
      </div>
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
            {currentQuestion.difficulty} / {difficultyPoints[currentQuestion.difficulty]} pts
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
                    ? "border-saints-line bg-saints-mist text-slate-500"
                    : "border-saints-line bg-white text-saints-ink hover:border-saints-red/40 hover:bg-saints-redSoft";

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
              {currentAnswer === currentQuestion.correct_answer ? "Correct" : "Not this time"}
            </p>
            <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-600">
              Answer details are shown after the final score.
            </p>
            <button
              type="button"
              onClick={goNext}
              className="mt-3 inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-saints-charcoal focus:outline-none focus:ring-4 focus:ring-saints-red/20"
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
