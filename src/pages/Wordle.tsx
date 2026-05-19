import { FormEvent, useEffect, useMemo, useState } from "react";
import { CalendarDays, Send, Trophy } from "lucide-react";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";
import { StatCard } from "../components/StatCard";
import { api, type FeedbackColor, type WordleState } from "../lib/api";

const tileColors: Record<FeedbackColor, string> = {
  green: "border-emerald-600 bg-emerald-600 text-white",
  yellow: "border-amber-400 bg-amber-400 text-slate-950",
  grey: "border-slate-400 bg-slate-400 text-white",
};

function formatGameDate(date: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(`${date}T12:00:00`));
}

export function Wordle() {
  const [state, setState] = useState<WordleState | null>(null);
  const [guess, setGuess] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadGame() {
      try {
        const response = await api.wordleToday();
        if (active) {
          setState(response);
        }
      } catch (caughtError) {
        if (active) {
          setError(caughtError instanceof Error ? caughtError.message : "Game failed to load.");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadGame();

    return () => {
      active = false;
    };
  }, []);

  const gameStatus = state?.result.status ?? "in_progress";
  const isComplete = gameStatus !== "in_progress";
  const wordLength = state?.game.wordLength ?? 5;
  const maxAttempts = state?.game.maxAttempts ?? 6;
  const guesses = state?.result.guesses ?? [];

  const statusText = useMemo(() => {
    if (state === null) {
      return loading ? "Loading daily game" : "Daily game unavailable";
    }

    if (state.result.status === "won") {
      return `Solved in ${state.result.attemptsUsed}`;
    }

    if (state.result.status === "lost") {
      return `Answer: ${state.result.answer?.toUpperCase()}`;
    }

    return `Attempt ${state.result.attemptsUsed + 1} of ${state.game.maxAttempts}`;
  }, [loading, state]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === null || isComplete) {
      return;
    }

    if (guess.length !== wordLength) {
      setError(`Enter ${wordLength} letters.`);
      return;
    }

    setError("");
    setSubmitting(true);

    try {
      const response = await api.submitWordleGuess(guess);
      setState(response);
      setGuess("");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Guess failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleGuessChange(value: string) {
    const normalized = value.replace(/[^a-z]/gi, "").slice(0, wordLength).toLowerCase();
    setGuess(normalized);
  }

  return (
    <PageContainer title="WORDLE" number="1">
      <Card>
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-red text-white">
            <CalendarDays aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="break-words text-xl font-black leading-tight text-slate-950">
              {state === null ? "Daily game" : formatGameDate(state.game.date)}
            </p>
            <p className="mt-2 text-base font-semibold leading-relaxed text-slate-600">
              {statusText}
            </p>
          </div>
          {gameStatus === "won" ? (
            <Trophy aria-hidden="true" className="h-7 w-7 text-saints-red" />
          ) : null}
        </div>
      </Card>

      <section aria-label="Wordle stats" className="grid grid-cols-3 gap-2">
        <StatCard label="Played" value={String(state?.stats.played ?? 0)} detail="Games" />
        <StatCard label="Wins" value={String(state?.stats.wins ?? 0)} detail="Solved" />
        <StatCard label="Losses" value={String(state?.stats.losses ?? 0)} detail="Missed" />
      </section>

      <Card>
        <div className="grid gap-2" aria-label="Wordle board">
          {Array.from({ length: maxAttempts }, (_, rowIndex) => {
            const submittedGuess = guesses[rowIndex];
            const isDraftRow = submittedGuess === undefined && rowIndex === guesses.length;
            const draft = isDraftRow && !isComplete ? guess.toUpperCase() : "";

            return (
              <div
                key={rowIndex}
                className="grid gap-2"
                style={{ gridTemplateColumns: `repeat(${wordLength}, minmax(0, 1fr))` }}
              >
                {Array.from({ length: wordLength }, (_, letterIndex) => {
                  const feedbackTile = submittedGuess?.feedback[letterIndex];
                  const letter = feedbackTile?.letter.toUpperCase() ?? draft[letterIndex] ?? "";
                  const colorClass =
                    feedbackTile !== undefined
                      ? tileColors[feedbackTile.color]
                      : "border-slate-300 bg-white text-slate-950";

                  return (
                    <div
                      key={letterIndex}
                      className={[
                        "flex aspect-square min-h-12 items-center justify-center rounded-xl border-2 text-xl font-black uppercase shadow-sm",
                        colorClass,
                      ].join(" ")}
                    >
                      {letter}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>

        <form className="mt-5 space-y-3 pb-20" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-sm font-black uppercase tracking-normal text-slate-600">
              Guess
            </span>
            <input
              value={guess.toUpperCase()}
              onChange={(event) => handleGuessChange(event.target.value)}
              className="mt-2 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-center text-xl font-black uppercase tracking-normal text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15 disabled:bg-slate-100"
              disabled={loading || isComplete}
              inputMode="text"
              autoComplete="off"
              maxLength={wordLength}
            />
          </label>

          {error ? (
            <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={loading || submitting || isComplete || guess.length !== wordLength}
            className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 text-base font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <Send aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            {submitting ? "Checking" : isComplete ? "Complete" : "Submit Guess"}
          </button>
        </form>
      </Card>
    </PageContainer>
  );
}
