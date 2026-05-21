import { FormEvent, useEffect, useMemo, useState } from "react";
import { Delete } from "lucide-react";
import { api, type FeedbackColor, type WordleState } from "../lib/api";

type GuessValidity = "empty" | "short" | "checking" | "valid" | "invalid";

const keyboardRows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];

const colorPriority: Record<FeedbackColor, number> = {
  grey: 1,
  yellow: 2,
  green: 3,
};

const tileColors: Record<FeedbackColor, string> = {
  green: "border-emerald-600 bg-emerald-600 text-white",
  yellow: "border-amber-400 bg-amber-400 text-slate-950",
  grey: "border-slate-500 bg-slate-500 text-white",
};

const keyboardColors: Record<FeedbackColor, string> = {
  green: "bg-emerald-600 text-white",
  yellow: "bg-amber-400 text-slate-950",
  grey: "bg-slate-500 text-white",
};

export function Wordle() {
  const [state, setState] = useState<WordleState | null>(null);
  const [guess, setGuess] = useState("");
  const [guessValidity, setGuessValidity] = useState<GuessValidity>("empty");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const gameStatus = state?.result.status ?? "in_progress";
  const isComplete = gameStatus !== "in_progress";
  const wordLength = state?.game.wordLength ?? 5;
  const maxAttempts = state?.game.maxAttempts ?? 6;
  const guesses = state?.result.guesses ?? [];
  const canSubmit = state !== null && !isComplete && guessValidity === "valid" && !submitting;

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

  useEffect(() => {
    let active = true;

    if (guess.length === 0) {
      setGuessValidity("empty");
      return;
    }

    if (guess.length < wordLength) {
      setGuessValidity("short");
      return;
    }

    setGuessValidity("checking");

    async function validateGuess() {
      try {
        const response = await api.validateWordleGuess(guess);
        if (active) {
          setGuessValidity(response.valid ? "valid" : "invalid");
        }
      } catch {
        if (active) {
          setGuessValidity("invalid");
        }
      }
    }

    void validateGuess();

    return () => {
      active = false;
    };
  }, [guess, wordLength]);

  const keyboardState = useMemo(() => {
    const statuses = new Map<string, FeedbackColor>();

    for (const submittedGuess of guesses) {
      for (const tile of submittedGuess.feedback) {
        const previous = statuses.get(tile.letter);
        if (
          previous === undefined ||
          colorPriority[tile.color] > colorPriority[previous]
        ) {
          statuses.set(tile.letter, tile.color);
        }
      }
    }

    return statuses;
  }, [guesses]);

  const statusText = useMemo(() => {
    if (state === null) {
      return loading ? "Loading daily game" : "Daily game unavailable";
    }

    if (state.result.status === "won") {
      return `Solved in ${state.result.attemptsUsed} - ${state.result.score} pts`;
    }

    if (state.result.status === "lost") {
      return `Answer: ${state.result.answer?.toUpperCase()}`;
    }

    return "";
  }, [loading, state]);

  function addLetter(letter: string) {
    setError("");
    setGuess((currentGuess) => {
      if (currentGuess.length >= wordLength) {
        return currentGuess;
      }
      return `${currentGuess}${letter.toLowerCase()}`;
    });
  }

  function removeLetter() {
    setError("");
    setGuess((currentGuess) => currentGuess.slice(0, -1));
  }

  async function submitGuess() {
    if (!canSubmit || state === null) {
      if (guess.length === wordLength && guessValidity === "invalid") {
        setError("Not in word list.");
      }
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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitGuess();
  }

  return (
    <section className="page-fade space-y-3" aria-label="Wordle game">
      <section className="max-w-full overflow-hidden rounded-[1.75rem] saints-card p-3">
        <form className="space-y-3 pb-2" onSubmit={handleSubmit}>
          {statusText ? (
            <p className="text-center text-base font-black text-slate-700">{statusText}</p>
          ) : null}
          {state ? (
            <div className="mx-auto flex w-fit items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-black uppercase text-slate-600">
              <span>{state.stats.points} Wordle pts</span>
              <span className="h-1 w-1 rounded-full bg-saints-red" aria-hidden="true" />
              <span>{state.stats.wins} wins</span>
            </div>
          ) : null}

          <div className="mx-auto grid max-w-[17rem] gap-1.5" aria-label="Wordle board">
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
                          "flex aspect-square min-h-10 items-center justify-center rounded-lg border-2 text-3xl font-black uppercase leading-none shadow-sm",
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

          <div className="min-h-6 text-center text-sm font-black">
            {guessValidity === "checking" ? (
              <span className="text-slate-500">Checking word</span>
            ) : guessValidity === "invalid" ? (
              <span className="text-saints-red">Not in word list</span>
            ) : guessValidity === "valid" ? (
              <span className="text-emerald-700">Valid word</span>
            ) : null}
          </div>

          <div className="space-y-1.5" aria-label="Wordle keyboard">
            {keyboardRows.map((row, rowIndex) => (
              <div
                key={row}
                className={[
                  "grid gap-1.5",
                  rowIndex === 1
                    ? "grid-cols-9 px-3"
                    : rowIndex === 2
                      ? "grid-cols-[1.3fr_repeat(7,1fr)_1.3fr]"
                      : "grid-cols-10",
                ].join(" ")}
              >
                {rowIndex === 2 ? (
                  <button
                    type="button"
                    onClick={() => void submitGuess()}
                    disabled={!canSubmit}
                    className="flex min-h-10 items-center justify-center rounded-lg bg-saints-red px-1 text-xs font-black uppercase text-white transition disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
                  >
                    Enter
                  </button>
                ) : null}

                {row.split("").map((letter) => {
                  const status = keyboardState.get(letter);
                  const colorClass =
                    status === undefined
                      ? "bg-slate-100 text-slate-950"
                      : keyboardColors[status];

                  return (
                    <button
                      key={letter}
                      type="button"
                      onClick={() => addLetter(letter)}
                      disabled={isComplete || submitting}
                      className={[
                        "flex min-h-10 items-center justify-center rounded-lg text-sm font-black uppercase shadow-sm transition focus:outline-none focus:ring-2 focus:ring-saints-red/30 disabled:cursor-not-allowed",
                        colorClass,
                      ].join(" ")}
                    >
                      {letter}
                    </button>
                  );
                })}

                {rowIndex === 2 ? (
                  <button
                    type="button"
                    aria-label="Delete letter"
                    onClick={removeLetter}
                    disabled={isComplete || submitting || guess.length === 0}
                    className="flex min-h-10 items-center justify-center rounded-lg bg-slate-100 text-slate-950 shadow-sm transition focus:outline-none focus:ring-2 focus:ring-saints-red/30 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                  >
                    <Delete aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </button>
                ) : null}
              </div>
            ))}
          </div>

          {error ? (
            <p className="rounded-2xl bg-red-50 px-3 py-2 text-center text-sm font-bold text-saints-red">
              {error}
            </p>
          ) : null}
        </form>
      </section>
    </section>
  );
}
