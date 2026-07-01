import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Delete, ExternalLink, LoaderCircle, Volume2, VolumeX } from "lucide-react";
import {
  api,
  type FeedbackColor,
  type WordleDefinition,
  type WordleGuess,
  type WordleState,
} from "../lib/api";

type GuessValidity = "empty" | "short" | "checking" | "valid" | "invalid";

type WindowWithWebkitAudio = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

const keyboardRows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
const largeTextStorageKey = "fultons-wordle-large-text";
const soundStorageKey = "fultons-wordle-sound";

const colorPriority: Record<FeedbackColor, number> = {
  grey: 1,
  yellow: 2,
  green: 3,
};

const tileColors: Record<FeedbackColor, string> = {
  green: "wordle-tile--green",
  yellow: "wordle-tile--yellow",
  grey: "wordle-tile--grey",
};

const keyboardColors: Record<FeedbackColor, string> = {
  green: "wordle-key--green",
  yellow: "wordle-key--yellow",
  grey: "wordle-key--grey",
};

const letterScores: Record<string, number> = {
  a: 1,
  e: 1,
  i: 1,
  o: 1,
  u: 1,
  l: 1,
  n: 1,
  s: 1,
  t: 1,
  r: 1,
  d: 2,
  g: 2,
  b: 3,
  c: 3,
  m: 3,
  p: 3,
  f: 4,
  h: 4,
  v: 4,
  w: 4,
  y: 4,
  k: 5,
  j: 8,
  x: 8,
  q: 10,
  z: 10,
};

function readStoredBoolean(key: string, fallback: boolean) {
  if (typeof window === "undefined") {
    return fallback;
  }

  const value = window.localStorage.getItem(key);
  if (value === null) {
    return fallback;
  }

  return value === "true";
}

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function getLetterScore(letter: string) {
  return letterScores[letter.toLowerCase()] ?? 1;
}

function buildKeyboardState(guesses: WordleGuess[]) {
  const statuses = new Map<string, FeedbackColor>();

  for (const submittedGuess of guesses) {
    for (const tile of submittedGuess.feedback) {
      const letter = tile.letter.toLowerCase();
      const previous = statuses.get(letter);
      if (
        previous === undefined ||
        colorPriority[tile.color] > colorPriority[previous]
      ) {
        statuses.set(letter, tile.color);
      }
    }
  }

  return statuses;
}

export function Wordle() {
  const [state, setState] = useState<WordleState | null>(null);
  const [guess, setGuess] = useState("");
  const [guessValidity, setGuessValidity] = useState<GuessValidity>("empty");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [definition, setDefinition] = useState<WordleDefinition | null>(null);
  const [definitionError, setDefinitionError] = useState("");
  const [definitionLoading, setDefinitionLoading] = useState(false);
  const [largeText, setLargeText] = useState(() =>
    readStoredBoolean(largeTextStorageKey, false),
  );
  const [soundEnabled, setSoundEnabled] = useState(() =>
    readStoredBoolean(soundStorageKey, true),
  );
  const [revealingRowIndex, setRevealingRowIndex] = useState<number | null>(null);
  const [revealedLetters, setRevealedLetters] = useState(0);
  const [keyboardOverride, setKeyboardOverride] = useState<Map<string, FeedbackColor> | null>(null);
  const [keyboardAnimatingLetter, setKeyboardAnimatingLetter] = useState("");
  const [animationMessage, setAnimationMessage] = useState("");
  const mountedRef = useRef(true);
  const audioContextRef = useRef<AudioContext | null>(null);

  const gameStatus = state?.result.status ?? "in_progress";
  const isComplete = gameStatus !== "in_progress";
  const wordLength = state?.game.wordLength ?? 5;
  const maxAttempts = state?.game.maxAttempts ?? 6;
  const guesses = state?.result.guesses ?? [];
  const isAnimatingReveal = revealingRowIndex !== null || keyboardOverride !== null || animationMessage !== "";
  const canSubmit =
    state !== null &&
    !isComplete &&
    guessValidity === "valid" &&
    !submitting &&
    !isAnimatingReveal;

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

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

    if (!isComplete) {
      setDefinition(null);
      setDefinitionError("");
      return;
    }

    setDefinitionLoading(true);
    setDefinitionError("");
    void api
      .wordleDefinition()
      .then((response) => {
        if (active) {
          setDefinition(response);
        }
      })
      .catch(() => {
        if (active) {
          setDefinitionError("Dictionary definition is unavailable right now.");
        }
      })
      .finally(() => {
        if (active) {
          setDefinitionLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [isComplete]);

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

  const keyboardState = useMemo(() => buildKeyboardState(guesses), [guesses]);
  const visibleKeyboardState = keyboardOverride ?? keyboardState;

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

  function getAudioContext() {
    if (!soundEnabled || typeof window === "undefined") {
      return null;
    }

    const AudioContextConstructor =
      window.AudioContext ?? (window as WindowWithWebkitAudio).webkitAudioContext;

    if (!AudioContextConstructor) {
      return null;
    }

    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContextConstructor();
    }

    void audioContextRef.current.resume?.();
    return audioContextRef.current;
  }

  function playTone(
    context: AudioContext,
    startFrequency: number,
    duration: number,
    delay: number,
    type: OscillatorType,
    volume: number,
    endFrequency = startFrequency,
  ) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const start = context.currentTime + delay;
    const end = start + duration;

    oscillator.type = type;
    oscillator.frequency.setValueAtTime(startFrequency, start);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(40, endFrequency), end);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, end);

    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(start);
    oscillator.stop(end + 0.02);
  }

  function playFeedbackSound(color: FeedbackColor) {
    const context = getAudioContext();
    if (!context) {
      return;
    }

    if (color === "green") {
      [523.25, 659.25, 783.99].forEach((frequency, index) => {
        playTone(context, frequency, 0.1, index * 0.055, "triangle", 0.08);
      });
      return;
    }

    if (color === "yellow") {
      playTone(context, 329.63, 0.34, 0, "sine", 0.055, 392);
      return;
    }

    playTone(context, 220, 0.24, 0, "sawtooth", 0.045, 146.83);
  }

  function addLetter(letter: string) {
    if (isComplete || submitting || isAnimatingReveal) {
      return;
    }

    setError("");
    setGuess((currentGuess) => {
      if (currentGuess.length >= wordLength) {
        return currentGuess;
      }
      return `${currentGuess}${letter.toLowerCase()}`;
    });
  }

  function removeLetter() {
    if (isComplete || submitting || isAnimatingReveal) {
      return;
    }

    setError("");
    setGuess((currentGuess) => currentGuess.slice(0, -1));
  }

  async function runRevealAnimation(response: WordleState, previousKeyboardState: Map<string, FeedbackColor>) {
    const latestGuess = response.result.guesses.at(-1);
    if (!latestGuess) {
      return;
    }

    const nextKeyboardState = buildKeyboardState(response.result.guesses);
    setKeyboardOverride(new Map(previousKeyboardState));
    setRevealingRowIndex(response.result.guesses.length - 1);
    setRevealedLetters(0);
    setAnimationMessage("Revealing your guess...");

    for (let index = 0; index < latestGuess.feedback.length; index += 1) {
      const tile = latestGuess.feedback[index];
      playFeedbackSound(tile.color);
      setRevealedLetters(index + 1);
      await wait(390);
      if (!mountedRef.current) {
        return;
      }
    }

    await wait(120);
    if (!mountedRef.current) {
      return;
    }

    setAnimationMessage("Updating the keyboard...");
    const seenLetters = new Set<string>();

    for (const tile of latestGuess.feedback) {
      const letter = tile.letter.toLowerCase();
      if (seenLetters.has(letter)) {
        continue;
      }
      seenLetters.add(letter);

      const nextStatus = nextKeyboardState.get(letter);
      const previousStatus = previousKeyboardState.get(letter);
      if (
        nextStatus === undefined ||
        (previousStatus !== undefined && colorPriority[nextStatus] < colorPriority[previousStatus])
      ) {
        continue;
      }

      setKeyboardAnimatingLetter(letter);
      setKeyboardOverride((current) => {
        const updated = new Map(current ?? previousKeyboardState);
        updated.set(letter, nextStatus);
        return updated;
      });
      await wait(220);
      if (!mountedRef.current) {
        return;
      }
      setKeyboardAnimatingLetter("");
      await wait(70);
    }

    setKeyboardOverride(null);
    setRevealingRowIndex(null);
    setRevealedLetters(0);
    setAnimationMessage("");
  }

  async function submitGuess() {
    if (!canSubmit || state === null) {
      if (guess.length === wordLength && guessValidity === "invalid") {
        setError("Not in word list.");
      }
      return;
    }

    const previousKeyboardState = new Map(keyboardState);
    setError("");
    setSubmitting(true);

    try {
      const response = await api.submitWordleGuess(guess);
      setState(response);
      setGuess("");
      await runRevealAnimation(response, previousKeyboardState);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Guess failed.");
    } finally {
      if (mountedRef.current) {
        setSubmitting(false);
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitGuess();
  }

  function toggleLargeText() {
    setLargeText((current) => {
      const next = !current;
      window.localStorage.setItem(largeTextStorageKey, String(next));
      return next;
    });
  }

  function toggleSound() {
    setSoundEnabled((current) => {
      const next = !current;
      window.localStorage.setItem(soundStorageKey, String(next));
      return next;
    });
  }

  return (
    <section
      className={["page-fade wordle-game", largeText ? "wordle-game--large-text" : ""].join(" ")}
      aria-label="Wordle game"
    >
      <section className="max-w-full overflow-hidden rounded-lg saints-card wordle-game-card p-2.5">
        <form className="space-y-2" onSubmit={handleSubmit}>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div className="min-w-0">
              <p className="text-[0.62rem] font-black uppercase tracking-[0.16em] text-saints-red">
                Wordle mode
              </p>
              <p className="text-xs font-bold text-slate-600">
                Animated reveals, sound cues and Scrabble-style tiles.
              </p>
            </div>
            <div className="flex shrink-0 gap-1.5">
              <button
                type="button"
                onClick={toggleLargeText}
                aria-pressed={largeText}
                className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[0.68rem] font-black uppercase text-slate-700 shadow-sm transition hover:border-saints-red hover:text-saints-red"
              >
                {largeText ? "Normal text" : "Large text"}
              </button>
              <button
                type="button"
                onClick={toggleSound}
                aria-pressed={soundEnabled}
                className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[0.68rem] font-black uppercase text-slate-700 shadow-sm transition hover:border-saints-red hover:text-saints-red"
              >
                {soundEnabled ? (
                  <Volume2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
                ) : (
                  <VolumeX aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.5} />
                )}
                {soundEnabled ? "Sound" : "Muted"}
              </button>
            </div>
          </div>

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

          <div className="wordle-board mx-auto" aria-label="Wordle board">
            {Array.from({ length: maxAttempts }, (_, rowIndex) => {
              const submittedGuess = guesses[rowIndex];
              const isDraftRow = submittedGuess === undefined && rowIndex === guesses.length;
              const isRevealingRow = revealingRowIndex === rowIndex;
              const draft = isDraftRow && !isComplete ? guess.toUpperCase() : "";

              return (
                <div
                  key={rowIndex}
                  className="wordle-board-row"
                  style={{ gridTemplateColumns: `repeat(${wordLength}, minmax(0, 1fr))` }}
                >
                  {Array.from({ length: wordLength }, (_, letterIndex) => {
                    const feedbackTile = submittedGuess?.feedback[letterIndex];
                    const letter = feedbackTile?.letter.toUpperCase() ?? draft[letterIndex] ?? "";
                    const shouldShowFeedback =
                      feedbackTile !== undefined &&
                      (!isRevealingRow || letterIndex < revealedLetters);
                    const colorClass =
                      feedbackTile !== undefined && shouldShowFeedback
                        ? tileColors[feedbackTile.color]
                        : "";
                    const isLatestReveal =
                      isRevealingRow && shouldShowFeedback && letterIndex === revealedLetters - 1;

                    return (
                      <div
                        key={letterIndex}
                        data-score={letter ? getLetterScore(letter) : undefined}
                        className={[
                          "wordle-tile",
                          letter ? "wordle-tile--filled" : "",
                          colorClass,
                          feedbackTile !== undefined && !shouldShowFeedback ? "wordle-tile--pending" : "",
                          shouldShowFeedback ? "wordle-tile--revealed" : "",
                          isLatestReveal ? "wordle-tile--revealing" : "",
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

          <div className="min-h-5 text-center text-xs font-black">
            {animationMessage ? (
              <span className="text-saints-red">{animationMessage}</span>
            ) : guessValidity === "checking" ? (
              <span className="text-slate-500">Checking word</span>
            ) : guessValidity === "invalid" ? (
              <span className="text-saints-red">Not in word list</span>
            ) : guessValidity === "valid" ? (
              <span className="text-emerald-700">Valid word</span>
            ) : null}
          </div>

          <div className="wordle-keyboard" aria-label="Wordle keyboard">
            {keyboardRows.map((row, rowIndex) => (
              <div
                key={row}
                className={[
                  "wordle-keyboard-row",
                  rowIndex === 1
                    ? "wordle-keyboard-row--middle"
                    : rowIndex === 2
                      ? "wordle-keyboard-row--bottom"
                      : "wordle-keyboard-row--top",
                ].join(" ")}
              >
                {rowIndex === 2 ? (
                  <button
                    type="button"
                    onClick={() => void submitGuess()}
                    disabled={!canSubmit}
                    className="wordle-key wordle-key--action wordle-key--enter"
                  >
                    Enter
                  </button>
                ) : null}

                {row.split("").map((letter) => {
                  const status = visibleKeyboardState.get(letter);
                  const colorClass = status === undefined ? "" : keyboardColors[status];
                  const isEliminated = status === "grey";

                  return (
                    <button
                      key={letter}
                      type="button"
                      onClick={() => addLetter(letter)}
                      disabled={isComplete || submitting || isAnimatingReveal || isEliminated}
                      className={[
                        "wordle-key",
                        colorClass,
                        isEliminated ? "wordle-key--eliminated" : "",
                        keyboardAnimatingLetter === letter ? "wordle-key--updating" : "",
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
                    disabled={isComplete || submitting || isAnimatingReveal || guess.length === 0}
                    className="wordle-key wordle-key--action"
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

        {isComplete ? (
          <section className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3" aria-label="Word definition">
            <div className="flex items-start gap-2">
              <BookOpen aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-saints-red" strokeWidth={2.4} />
              <div className="min-w-0">
                <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                  Today's word
                </p>
                <h2 className="mt-1 text-xl font-black uppercase text-slate-950">
                  {definition?.word ?? state?.result.answer}
                </h2>
                {definitionLoading ? (
                  <p className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-slate-500">
                    <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
                    Loading dictionary definition
                  </p>
                ) : definition?.definition ? (
                  <>
                    {definition.partOfSpeech ? (
                      <p className="mt-1 text-xs font-black italic text-slate-500">
                        {definition.partOfSpeech}
                      </p>
                    ) : null}
                    <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-700">
                      {definition.definition}
                    </p>
                    <a
                      href={definition.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-black text-saints-red underline-offset-2 hover:underline"
                    >
                      Dictionary source
                      <ExternalLink aria-hidden="true" className="h-3 w-3" />
                    </a>
                  </>
                ) : (
                  <p className="mt-2 text-sm font-semibold text-slate-500">
                    {definitionError || "Dictionary definition is unavailable for this word."}
                  </p>
                )}
              </div>
            </div>
          </section>
        ) : null}
      </section>
    </section>
  );
}
