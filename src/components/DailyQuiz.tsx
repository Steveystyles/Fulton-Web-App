import { ArrowRight, Check, CircleAlert, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type DailyQuizQuestion, type DailyQuizResult, type QuizDifficulty } from "../lib/api";
import { Card } from "./Card";

type QuizCategory = "football" | "general";

type DailyQuizProps = {
  category: QuizCategory;
  storageScope: number;
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
};

type StoredQuizState = {
  currentIndex: number;
  answers: string[];
};

const emptyQuizState: StoredQuizState = { currentIndex: 0, answers: [] };
const difficultyPoints: Record<QuizDifficulty, number> = { easy: 1, medium: 3, hard: 5 };
const answerLetters = ["A", "B", "C", "D"];
const difficultyClasses: Record<QuizDifficulty, string> = {
  easy: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  hard: "bg-saints-redSoft text-saints-red ring-red-200",
};
const difficultyLabels: Record<QuizDifficulty, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

function storageKey(category: QuizCategory, storageScope: number, quizDate?: string) {
  return quizDate ? `fultons:daily-quiz:v4:${storageScope}:${category}:${quizDate}` : "";
}

function readStoredState(key: string, questions: DailyQuizQuestion[]): StoredQuizState {
  try {
    const raw = window.localStorage.getItem(key);
    const payload = raw ? (JSON.parse(raw) as Partial<StoredQuizState>) : {};
    const storedAnswers = Array.isArray(payload.answers) ? payload.answers : [];
    const answers: string[] = [];
    for (let index = 0; index < Math.min(storedAnswers.length, questions.length); index += 1) {
      const choiceId = storedAnswers[index];
      if (
        typeof choiceId !== "string" ||
        !questions[index].answers.some((choice) => choice.id === choiceId)
      ) {
        break;
      }
      answers.push(choiceId);
    }
    return {
      currentIndex: Math.min(Math.max(0, Number(payload.currentIndex) || 0), answers.length),
      answers,
    };
  } catch {
    return emptyQuizState;
  }
}

function formattedDate(quizDate?: string) {
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

function categoryTitle(category: QuizCategory) {
  return category === "football" ? "Football quiz" : "General knowledge quiz";
}

export function DailyQuiz({
  category,
  storageScope,
  quizDate,
  questions,
  loading,
  error,
}: DailyQuizProps) {
  const key = useMemo(
    () => storageKey(category, storageScope, quizDate),
    [category, quizDate, storageScope],
  );
  const [quizState, setQuizState] = useState<StoredQuizState>(emptyQuizState);
  const [savedResult, setSavedResult] = useState<DailyQuizResult | null>(null);
  const [scoreError, setScoreError] = useState("");
  const [scoreRetryVersion, setScoreRetryVersion] = useState(0);

  useEffect(() => {
    setQuizState(key ? readStoredState(key, questions) : emptyQuizState);
    setSavedResult(null);
    setScoreError("");
  }, [key, questions]);

  useEffect(() => {
    if (!key) {
      return;
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(quizState));
    } catch {
      // The active game remains usable when browser storage is unavailable.
    }
  }, [key, quizState]);

  const currentQuestion = questions[quizState.currentIndex];
  const currentChoiceId = currentQuestion ? quizState.answers[quizState.currentIndex] ?? "" : "";
  const isComplete = questions.length > 0 && quizState.currentIndex >= questions.length;
  const answeredCount = Math.min(quizState.answers.length, questions.length);
  const progressPercent = questions.length > 0 ? (answeredCount / questions.length) * 100 : 0;

  useEffect(() => {
    let active = true;
    if (!isComplete || !quizDate || quizState.answers.length !== questions.length || savedResult) {
      return;
    }

    setScoreError("");
    void api
      .submitDailyQuizResult({
        date: quizDate,
        category,
        answers: questions.map((question, index) => ({
          questionId: question.id,
          choiceId: quizState.answers[index],
        })),
      })
      .then((response) => {
        if (active) {
          setSavedResult(response.result);
        }
      })
      .catch((caughtError: unknown) => {
        if (active) {
          setScoreError(caughtError instanceof Error ? caughtError.message : "Score was not saved.");
        }
      });

    return () => {
      active = false;
    };
  }, [category, isComplete, questions, quizDate, quizState.answers, savedResult, scoreRetryVersion]);

  function chooseAnswer(choiceId: string) {
    if (!currentQuestion || currentChoiceId) {
      return;
    }
    setQuizState((current) => {
      const answers = current.answers.slice();
      answers[current.currentIndex] = choiceId;
      return { ...current, answers };
    });
  }

  function goNext() {
    setQuizState((current) => ({
      ...current,
      currentIndex: Math.min(current.currentIndex + 1, questions.length),
    }));
  }

  function retryScoreSave() {
    setScoreError("");
    setScoreRetryVersion((current) => current + 1);
  }

  if (loading) {
    return (
      <Card>
        <div className="flex min-h-28 items-center justify-center gap-2 text-sm font-black text-slate-500">
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
          Loading today's quiz
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-start gap-3">
          <CircleAlert aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-saints-red" />
          <div>
            <p className="font-black text-slate-950">Quiz unavailable</p>
            <p className="mt-1 text-sm font-semibold text-slate-600">{error.message}</p>
          </div>
        </div>
      </Card>
    );
  }

  if (questions.length === 0) {
    return (
      <Card>
        <p className="text-sm font-semibold text-slate-600">Today's quiz is not available yet.</p>
      </Card>
    );
  }

  if (isComplete) {
    return (
      <Card>
        <div className="text-center">
          <p className="text-xs font-black uppercase text-saints-red">{formattedDate(quizDate)}</p>
          <h2 className="mt-2 text-2xl font-black text-slate-950">Final score</h2>
          {savedResult ? (
            <p className="mt-2 text-5xl font-black text-saints-black">
              {savedResult.score} / {savedResult.maxScore}
            </p>
          ) : scoreError ? (
            <p className="mt-4 text-sm font-black text-saints-red">Score unavailable</p>
          ) : (
            <p className="mt-4 inline-flex items-center gap-2 text-sm font-black text-slate-500">
              <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
              Checking your answers
            </p>
          )}
          <p className="mt-3 text-sm font-semibold leading-relaxed text-slate-600">
            Easy questions are worth 1 point, medium 3, and hard 5. A perfect round earns 3 bonus points.
          </p>
          {(savedResult?.bonusPoints ?? 0) > 0 ? (
            <p className="mx-auto mt-3 inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1.5 text-sm font-black text-amber-700 ring-1 ring-amber-200">
              <Sparkles aria-hidden="true" className="h-4 w-4" />
              Perfect round +{savedResult?.bonusPoints ?? 0}
            </p>
          ) : null}
          {scoreError ? (
            <div className="mt-3 rounded-lg bg-red-50 px-3 py-3 text-saints-red">
              <p className="text-sm font-bold">{scoreError}</p>
              <button
                type="button"
                onClick={retryScoreSave}
                className="mt-3 inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-saints-red px-4 text-sm font-black text-white transition hover:bg-saints-redDark focus:outline-none focus:ring-4 focus:ring-saints-red/20"
              >
                <RotateCcw aria-hidden="true" className="h-4 w-4" />
                Retry saving score
              </button>
            </div>
          ) : null}
          {savedResult?.adjudications.length ? (
            <div className="mt-5 space-y-3 text-left">
              {savedResult.adjudications.map((adjudication, index) => {
                const question = questions.find(
                  (candidate) => candidate.id === adjudication.questionId,
                );
                return (
                  <div
                    key={adjudication.questionId}
                    className={[
                      "rounded-2xl border p-3.5",
                      adjudication.correct
                        ? "border-emerald-200 bg-emerald-50"
                        : "border-red-200 bg-red-50",
                    ].join(" ")}
                  >
                    <p className="text-xs font-black uppercase tracking-wide text-slate-500">
                      Question {index + 1}
                    </p>
                    {question ? (
                      <p className="mt-1 text-sm font-black text-slate-950">
                        {question.question}
                      </p>
                    ) : null}
                    <p className="mt-2 text-sm font-black text-slate-950">
                      {adjudication.correct
                        ? "Correct"
                        : `Correct answer: ${adjudication.correctAnswer}`}
                    </p>
                    <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
                      {adjudication.explanation}
                    </p>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-0">
      <div className="border-b border-slate-200 bg-slate-50/80 px-4 py-3">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[0.68rem] font-black uppercase tracking-wide text-saints-red">
              {formattedDate(quizDate)}
            </p>
            <h2 className="mt-1 text-lg font-black leading-tight text-slate-950">
              {categoryTitle(category)}
            </h2>
            <p className="mt-1 text-sm font-semibold text-slate-500">
              Question {quizState.currentIndex + 1} of {questions.length}
            </p>
          </div>
          <span
            className={[
              "shrink-0 rounded-full px-3 py-1.5 text-xs font-black uppercase ring-1",
              difficultyClasses[currentQuestion.difficulty],
            ].join(" ")}
          >
            {difficultyLabels[currentQuestion.difficulty]} · {difficultyPoints[currentQuestion.difficulty]} pts
          </span>
        </header>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white ring-1 ring-slate-200">
          <div
            className="h-full rounded-full bg-saints-red transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
            aria-hidden="true"
          />
        </div>
      </div>

      <div className="space-y-5 p-4 sm:p-5">
        <div className="rounded-2xl bg-white">
          <p className="text-xs font-black uppercase tracking-wide text-slate-400">Question</p>
          <p className="mt-2 text-xl font-black leading-snug text-slate-950">
            {currentQuestion.question}
          </p>
        </div>

        <div className="grid gap-2.5" aria-label="Answer choices">
          {currentQuestion.answers.map((answer, answerIndex) => {
            const isSelected = currentChoiceId === answer.id;
            const isMuted = Boolean(currentChoiceId) && !isSelected;
            return (
              <button
                key={answer.id}
                type="button"
                onClick={() => chooseAnswer(answer.id)}
                disabled={Boolean(currentChoiceId)}
                className={[
                  "group flex min-h-14 items-center justify-between gap-3 rounded-2xl border px-3.5 py-3 text-left text-base font-semibold leading-snug transition focus:outline-none focus:ring-4 focus:ring-saints-red/20 disabled:cursor-default",
                  isSelected
                    ? "border-saints-black bg-saints-black text-white shadow-sm"
                    : isMuted
                      ? "border-slate-200 bg-slate-50 text-slate-500"
                      : "border-slate-200 bg-white text-saints-ink shadow-sm hover:border-saints-red/40 hover:bg-saints-redSoft",
                ].join(" ")}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    className={[
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-black ring-1",
                      isSelected
                        ? "bg-white/20 text-white ring-white/30"
                        : "bg-slate-100 text-slate-600 ring-slate-200 group-hover:bg-white",
                    ].join(" ")}
                  >
                    {answerLetters[answerIndex] ?? answerIndex + 1}
                  </span>
                  <span className="min-w-0">{answer.text}</span>
                </span>
                {isSelected ? <Check aria-hidden="true" className="h-5 w-5 shrink-0" /> : null}
              </button>
            );
          })}
        </div>

        {currentChoiceId ? (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3.5">
            <p className="text-base font-black text-slate-950">Answer locked in</p>
            <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
              Your answers are graded securely after the final question.
            </p>
            <button
              type="button"
              onClick={goNext}
              className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-saints-charcoal focus:outline-none focus:ring-4 focus:ring-saints-red/20"
            >
              {quizState.currentIndex === questions.length - 1 ? "See final score" : "Next question"}
              <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
