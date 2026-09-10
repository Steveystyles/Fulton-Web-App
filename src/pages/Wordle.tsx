import { DialogPortal } from "../components/DialogPortal";
import { DailyJourney } from "../components/DailyJourney";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type TouchEvent,
  type WheelEvent,
} from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Delete,
  ExternalLink,
  LoaderCircle,
  Trophy,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  type FeedbackColor,
  type WordleGuess,
  type WordleState,
} from "../lib/api";
import type { WordleDefinition } from "../lib/api";

type GuessValidity = "empty" | "short" | "checking" | "valid" | "invalid";
type WindowWithWebkitAudio = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

const keyboardRows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
const largePrintStorageKey = "fultons-wordle-large-print";
const soundStorageKey = "fultons-wordle-sound";
const maxWordleLevel = 20;

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

function difficultyBadgeClasses(level: number) {
  if (level <= 5) {
    return "border border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (level <= 10) {
    return "border border-sky-200 bg-sky-50 text-sky-800";
  }
  if (level <= 15) {
    return "border border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border border-rose-200 bg-rose-50 text-rose-800";
}

function readLargePrintPreference() {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    return window.localStorage.getItem(largePrintStorageKey) === "1";
  } catch {
    return false;
  }
}

function writeLargePrintPreference(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(largePrintStorageKey, enabled ? "1" : "0");
  } catch {
    // Keep the toggle usable even when browser storage is unavailable.
  }
}

function readSoundPreference() {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    return window.localStorage.getItem(soundStorageKey) === "1";
  } catch {
    return false;
  }
}

function writeSoundPreference(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(soundStorageKey, enabled ? "1" : "0");
  } catch {
    // Sound still toggles for the current session if storage is unavailable.
  }
}

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function buildKeyboardState(guesses: WordleGuess[]) {
  const statuses = new Map<string, FeedbackColor>();

  for (const submittedGuess of guesses) {
    for (const tile of submittedGuess.feedback) {
      const letter = tile.letter.toLowerCase();
      const previous = statuses.get(letter);
      if (previous === undefined || colorPriority[tile.color] > colorPriority[previous]) {
        statuses.set(letter, tile.color);
      }
    }
  }

  return statuses;
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

function DictionaryDefinitionCard({
  compact = false,
  definition,
  error,
  loading,
  largePrint,
}: {
  compact?: boolean;
  definition: WordleDefinition | null;
  error: string;
  loading: boolean;
  largePrint: boolean;
}) {
  const word = definition?.word ?? "";
  const definitionItems =
    definition?.definitions?.filter((item) => item.definition.trim().length > 0) ??
    (definition?.definition
      ? [{ definition: definition.definition, partOfSpeech: definition.partOfSpeech }]
      : []);
  const visibleDefinitions = definitionItems.slice(0, compact ? 1 : 3);
  const sourceUrl = definition?.sourceUrl ?? "https://dictionaryapi.dev/";
  const termClass = compact ? (largePrint ? "text-2xl" : "text-xl") : largePrint ? "text-3xl" : "text-2xl";
  const bodyClass = compact
    ? largePrint
      ? "text-[0.95rem] leading-6"
      : "text-sm leading-relaxed"
    : largePrint
      ? "text-base leading-7"
      : "text-sm leading-relaxed";
  const metaClass = largePrint ? "text-sm" : "text-xs";
  const articleClass = compact
    ? "text-left"
    : "rounded-lg border border-slate-200 bg-white p-4 text-left shadow-sm";
  const iconClass = compact
    ? "flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-saints-red ring-1 ring-red-100"
    : "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-saints-redSoft text-saints-red";

  return (
    <article className={articleClass}>
      <div className={["flex items-start", compact ? "gap-2.5" : "gap-3"].join(" ")}>
        <div className={iconClass}>
          <BookOpen aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
        </div>
        <div className="min-w-0">
          <p className="text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
            Dictionary
          </p>
          <h2 className={["mt-1 font-black lowercase leading-none text-slate-950", termClass].join(" ")}>
            {word || "word"}
          </h2>
          {definition?.partOfSpeech ? (
            <p className={["mt-2 font-black italic text-saints-red", metaClass].join(" ")}>
              {definition.partOfSpeech}
            </p>
          ) : null}
        </div>
      </div>

      {loading ? (
        <p className={["mt-4 flex items-center gap-2 font-semibold text-slate-500", bodyClass].join(" ")}>
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
          Loading dictionary definition
        </p>
      ) : visibleDefinitions.length > 0 ? (
        <>
          <ol className={["mt-4 space-y-3 border-l-4 border-saints-red/70 pl-3 font-serif text-slate-800", bodyClass].join(" ")}>
            {visibleDefinitions.map((item, index) => (
              <li key={`${item.definition}-${index}`} className="min-w-0">
                <p>{item.definition}</p>
                {item.partOfSpeech && item.partOfSpeech !== definition?.partOfSpeech ? (
                  <p className={["mt-1 font-sans font-black italic text-saints-red", metaClass].join(" ")}>
                    {item.partOfSpeech}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className={["mt-3 inline-flex items-center gap-1 font-black text-saints-red underline-offset-2 hover:underline", metaClass].join(" ")}
          >
            Dictionary source
            <ExternalLink aria-hidden="true" className="h-3 w-3" />
          </a>
        </>
      ) : (
        <p className={["mt-4 font-semibold text-slate-500", bodyClass].join(" ")}>
          {error || "Dictionary definition is unavailable for this word."}
        </p>
      )}
    </article>
  );
}

function SavedWordleStats({ state }: { state: WordleState }) {
  const scoreLabel = state.result.score > 0 ? `+${state.result.score}` : String(state.result.score);
  const playedLabel = state.stats.played === 1 ? "game" : "games";

  const stats = [
    { label: "Today", value: `${scoreLabel} pts` },
    { label: "All-time", value: `${state.stats.points} pts` },
    { label: "Solve streak", value: state.stats.currentSolveStreak },
    { label: "Best streak", value: state.stats.bestSolveStreak },
  ];

  return (
    <section
      className="mt-4 rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
      aria-label="Saved Wordle score"
    >
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-saints-redSoft text-saints-red">
          <Trophy aria-hidden="true" className="h-4 w-4" strokeWidth={2.5} />
        </span>
        <div className="min-w-0">
          <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
            Score saved
          </p>
          <p className="mt-0.5 text-sm font-bold text-slate-600">
            {state.stats.wins} wins from {state.stats.played} {playedLabel}
          </p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-lg bg-slate-50 px-3 py-2 text-center ring-1 ring-slate-200">
            <dt className="text-[0.62rem] font-black uppercase tracking-normal text-slate-500">
              {stat.label}
            </dt>
            <dd className="mt-1 text-xl font-black leading-none text-slate-950">{stat.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Wordle() {
  const boardScrollRef = useRef<HTMLDivElement | null>(null);
  const wheelGestureLockedRef = useRef(false);
  const wheelUnlockTimeoutRef = useRef<number | null>(null);
  const touchStartYRef = useRef<number | null>(null);
  const touchGestureHandledRef = useRef(false);
  const mountedRef = useRef(true);
  const audioContextRef = useRef<AudioContext | null>(null);
  const [state, setState] = useState<WordleState | null>(null);
  const [guess, setGuess] = useState("");
  const [guessValidity, setGuessValidity] = useState<GuessValidity>("empty");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [definition, setDefinition] = useState<WordleDefinition | null>(null);
  const [definitionError, setDefinitionError] = useState("");
  const [definitionLoading, setDefinitionLoading] = useState(false);
  const [largePrint, setLargePrint] = useState(readLargePrintPreference);
  const [soundEnabled, setSoundEnabled] = useState(readSoundPreference);
  const [winDialogDismissed, setWinDialogDismissed] = useState(false);
  const [lossDialogDismissed, setLossDialogDismissed] = useState(false);
  const [revealingRowIndex, setRevealingRowIndex] = useState<number | null>(null);
  const [revealedLetters, setRevealedLetters] = useState(0);
  const [keyboardOverride, setKeyboardOverride] = useState<Map<string, FeedbackColor> | null>(null);
  const [keyboardAnimatingLetter, setKeyboardAnimatingLetter] = useState("");
  const [animationMessage, setAnimationMessage] = useState("");
  const [largeBoardWindowHeight, setLargeBoardWindowHeight] = useState<number | null>(null);
  const [rowWindowStartIndex, setRowWindowStartIndex] = useState(0);

  const gameStatus = state?.result.status ?? "in_progress";
  const isComplete = gameStatus !== "in_progress";
  const wordLength = state?.game.wordLength ?? 5;
  const maxAttempts = state?.game.maxAttempts ?? 6;
  const guesses = state?.result.guesses ?? [];
  const activeRowIndex = isComplete
    ? Math.max(0, guesses.length - 1)
    : Math.min(guesses.length, maxAttempts - 1);
  const largeVisibleRowCount = Math.min(2, maxAttempts);
  const maxStartRowIndex = Math.max(0, maxAttempts - largeVisibleRowCount);
  const defaultVisibleStartRowIndex = largePrint
    ? Math.min(maxStartRowIndex, Math.max(0, activeRowIndex - largeVisibleRowCount + 1))
    : 0;
  const visibleStartRowIndex = largePrint
    ? Math.min(maxStartRowIndex, Math.max(0, rowWindowStartIndex))
    : 0;
  const rowScrollState = {
    canScrollDown: largePrint && visibleStartRowIndex < maxStartRowIndex,
    canScrollUp: largePrint && visibleStartRowIndex > 0,
  };
  const visibleRowIndexes = Array.from(
    {
      length: largePrint ? largeVisibleRowCount : maxAttempts,
    },
    (_, offset) => (largePrint ? visibleStartRowIndex + offset : offset),
  ).filter((rowIndex) => rowIndex >= 0 && rowIndex < maxAttempts);
  const isAnimatingReveal =
    revealingRowIndex !== null || keyboardOverride !== null || animationMessage !== "";
  const canSubmit =
    state !== null && !isComplete && guessValidity === "valid" && !submitting && !isAnimatingReveal;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    writeLargePrintPreference(largePrint);
  }, [largePrint]);

  useEffect(() => {
    writeSoundPreference(soundEnabled);
  }, [soundEnabled]);

  useEffect(() => {
    setRowWindowStartIndex(defaultVisibleStartRowIndex);
  }, [defaultVisibleStartRowIndex]);

  useEffect(
    () => () => {
      if (wheelUnlockTimeoutRef.current !== null) {
        window.clearTimeout(wheelUnlockTimeoutRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (gameStatus === "won") {
      setWinDialogDismissed(false);
    }
  }, [gameStatus, state?.game.date]);

  useEffect(() => {
    if (gameStatus === "lost") {
      setLossDialogDismissed(false);
    }
  }, [gameStatus, state?.game.date]);

  useEffect(() => {
    let active = true;

    async function loadGame() {
      try {
        let response: WordleState;
        try {
          response = await api.wordleToday();
        } catch (caughtError) {
          if (!(caughtError instanceof ApiError) || caughtError.status !== 404) {
            throw caughtError;
          }
          response = await api.startWordle();
        }
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
      setDefinitionLoading(false);
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

  useEffect(() => {
    const board = boardScrollRef.current;
    if (board === null) {
      return;
    }

    board.scrollTo({ top: 0, behavior: "auto" });
  }, [largePrint, visibleStartRowIndex]);

  useEffect(() => {
    if (!largePrint) {
      setLargeBoardWindowHeight(null);
      return;
    }

    const board = boardScrollRef.current;
    if (board === null) {
      return;
    }

    const updateBoardWindowHeight = () => {
      const row = board.querySelector<HTMLElement>("[data-wordle-row]");
      const rowGroup = board.firstElementChild;
      if (row === null || !(rowGroup instanceof HTMLElement)) {
        return;
      }

      const visibleRows = largeVisibleRowCount;
      const rowGap = Number.parseFloat(window.getComputedStyle(rowGroup).rowGap || "0") || 0;
      const rowHeight = row.getBoundingClientRect().height;
      if (rowHeight <= 0 || visibleRows <= 0) {
        return;
      }

      const verticalBuffer = Math.max(rowGap, 6);
      const nextHeight = Math.ceil(rowHeight * visibleRows + rowGap * (visibleRows - 1) + verticalBuffer * 2 - 4);
      setLargeBoardWindowHeight((currentHeight) =>
        currentHeight !== null && Math.abs(currentHeight - nextHeight) < 1 ? currentHeight : nextHeight,
      );
    };

    updateBoardWindowHeight();
    const animationFrame = window.requestAnimationFrame(updateBoardWindowHeight);
    const settledLayoutTimer = window.setTimeout(updateBoardWindowHeight, 250);
    window.addEventListener("resize", updateBoardWindowHeight);

    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateBoardWindowHeight);
    resizeObserver?.observe(board);
    if (board.firstElementChild instanceof HTMLElement) {
      resizeObserver?.observe(board.firstElementChild);
    }

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.clearTimeout(settledLayoutTimer);
      window.removeEventListener("resize", updateBoardWindowHeight);
      resizeObserver?.disconnect();
    };
  }, [largePrint, largeVisibleRowCount, wordLength]);

  const addLetter = useCallback(
    (letter: string) => {
      if (isComplete || submitting || isAnimatingReveal) {
        return;
      }
      const nextLetter = letter.slice(0, 1).toLowerCase();
      if (!/^[a-z]$/.test(nextLetter)) {
        return;
      }
      setError("");
      setGuess((currentGuess) => {
        if (currentGuess.length >= wordLength) {
          return currentGuess;
        }
        return `${currentGuess}${nextLetter}`;
      });
    },
    [isAnimatingReveal, isComplete, submitting, wordLength],
  );

  const removeLetter = useCallback(() => {
    if (isComplete || submitting || isAnimatingReveal) {
      return;
    }
    setError("");
    setGuess((currentGuess) => currentGuess.slice(0, -1));
  }, [isAnimatingReveal, isComplete, submitting]);

  const keyboardState = useMemo(() => buildKeyboardState(guesses), [guesses]);
  const visibleKeyboardState = keyboardOverride ?? keyboardState;

  const getAudioContext = useCallback((enabled = soundEnabled) => {
    if (!enabled || typeof window === "undefined") {
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
  }, [soundEnabled]);

  const handleSoundToggle = useCallback(() => {
    if (!soundEnabled) {
      getAudioContext(true);
    }
    setSoundEnabled((current) => !current);
  }, [getAudioContext, soundEnabled]);

  const playFeedbackSound = useCallback(
    (color: FeedbackColor) => {
      const context = getAudioContext();
      if (context === null) {
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
    },
    [getAudioContext],
  );

  const runRevealAnimation = useCallback(
    async (response: WordleState, previousKeyboardState: Map<string, FeedbackColor>) => {
      const latestGuess = response.result.guesses[response.result.guesses.length - 1];
      if (latestGuess === undefined) {
        return;
      }

      const nextKeyboardState = buildKeyboardState(response.result.guesses);

      if (prefersReducedMotion()) {
        setKeyboardOverride(null);
        setRevealingRowIndex(null);
        setRevealedLetters(0);
        setAnimationMessage("");
        setKeyboardAnimatingLetter("");
        return;
      }

      setKeyboardOverride(new Map(previousKeyboardState));
      setRevealingRowIndex(response.result.guesses.length - 1);
      setRevealedLetters(0);
      setAnimationMessage("Revealing your guess");

      for (let index = 0; index < latestGuess.feedback.length; index += 1) {
        const tile = latestGuess.feedback[index];
        playFeedbackSound(tile.color);
        setRevealedLetters(index + 1);
        await wait(330);
        if (!mountedRef.current) {
          return;
        }
      }

      await wait(100);
      if (!mountedRef.current) {
        return;
      }

      setAnimationMessage("Updating keyboard");
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
        await wait(180);
        if (!mountedRef.current) {
          return;
        }
        setKeyboardAnimatingLetter("");
        await wait(50);
      }

      setKeyboardOverride(null);
      setRevealingRowIndex(null);
      setRevealedLetters(0);
      setAnimationMessage("");
      setKeyboardAnimatingLetter("");
    },
    [playFeedbackSound],
  );

  const submitGuess = useCallback(async () => {
    if (!canSubmit || state === null) {
      if (guess.length === wordLength && guessValidity === "invalid") {
        setError("Not in word list.");
      }
      return;
    }

    const previousKeyboardState = new Map(keyboardState);
    getAudioContext();
    setError("");
    setSubmitting(true);

    try {
      const response = await api.submitWordleGuess({
        guess,
        expectedAttemptsUsed: state.result.attemptsUsed,
        expectedGameDate: state.game.date,
      });
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
  }, [canSubmit, getAudioContext, guess, guessValidity, keyboardState, runRevealAnimation, state, wordLength]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      if (event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey || event.isComposing ||
          tagName === "INPUT" || tagName === "TEXTAREA" || target?.isContentEditable ||
          target?.closest("button, a, select, summary, [role='button']") || document.querySelector('[aria-modal="true"]')) {
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        void submitGuess();
        return;
      }

      if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        removeLetter();
        return;
      }

      if (/^[a-zA-Z]$/.test(event.key)) {
        event.preventDefault();
        addLetter(event.key);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [addLetter, removeLetter, submitGuess]);

  const statusText = useMemo(() => {
    if (state === null) {
      return loading ? "Loading daily game" : "Daily game unavailable";
    }

    if (state.result.status === "won") {
      const guessLabel = state.result.attemptsUsed === 1 ? "guess" : "guesses";
      return `Solved in ${state.result.attemptsUsed} ${guessLabel} · ${state.result.score} points`;
    }

    if (state.result.status === "lost") {
      return `Answer: ${state.result.answer?.toUpperCase() ?? "Unavailable"} · ${state.result.score} points`;
    }

    return "";
  }, [loading, state]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitGuess();
  }

  const moveBoardRows = useCallback(
    (direction: 1 | -1) => {
      if (!largePrint) {
        return;
      }

      setRowWindowStartIndex((currentIndex) =>
        Math.min(maxStartRowIndex, Math.max(0, currentIndex + direction)),
      );
    },
    [largePrint, maxStartRowIndex],
  );

  const releaseWheelGestureAfterBurst = useCallback(() => {
    if (wheelUnlockTimeoutRef.current !== null) {
      window.clearTimeout(wheelUnlockTimeoutRef.current);
    }
    wheelUnlockTimeoutRef.current = window.setTimeout(() => {
      wheelGestureLockedRef.current = false;
      wheelUnlockTimeoutRef.current = null;
    }, 240);
  }, []);

  const handleBoardWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      if (!largePrint || event.deltaY === 0) {
        return;
      }

      releaseWheelGestureAfterBurst();
      if (wheelGestureLockedRef.current) {
        return;
      }

      wheelGestureLockedRef.current = true;
      moveBoardRows(event.deltaY > 0 ? 1 : -1);
    },
    [largePrint, moveBoardRows, releaseWheelGestureAfterBurst],
  );

  const handleRowControlClick = useCallback(
    (direction: 1 | -1) => {
      if (!largePrint) {
        return;
      }

      moveBoardRows(direction);
    },
    [largePrint, moveBoardRows],
  );

  const handleBoardTouchStart = useCallback(
    (event: TouchEvent<HTMLDivElement>) => {
      if (!largePrint || event.touches.length === 0) {
        return;
      }

      touchStartYRef.current = event.touches[0].clientY;
      touchGestureHandledRef.current = false;
    },
    [largePrint],
  );

  const handleBoardTouchMove = useCallback(
    (event: TouchEvent<HTMLDivElement>) => {
      if (!largePrint || touchStartYRef.current === null || event.touches.length === 0) {
        return;
      }

      const deltaY = touchStartYRef.current - event.touches[0].clientY;
      if (Math.abs(deltaY) < 24) {
        return;
      }

      event.preventDefault();
      if (touchGestureHandledRef.current) {
        return;
      }

      touchGestureHandledRef.current = true;
      moveBoardRows(deltaY > 0 ? 1 : -1);
    },
    [largePrint, moveBoardRows],
  );

  const handleBoardTouchEnd = useCallback(
    () => {
      touchStartYRef.current = null;
      touchGestureHandledRef.current = false;
    },
    [],
  );

  const statusTextClass = largePrint ? "text-lg" : "text-base";
  const rowControlButtonClass =
    "flex h-10 w-full items-center justify-center text-slate-700 transition hover:bg-white hover:text-saints-red focus:outline-none focus:ring-4 focus:ring-saints-red/15 disabled:cursor-not-allowed disabled:text-slate-300";
  const controlBarClass =
    "mx-auto w-full max-w-[22rem] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm";
  const settingsRowClass = state
    ? "grid grid-cols-[minmax(0,5.6rem)_minmax(0,1fr)_3.15rem] divide-x divide-slate-200 min-[380px]:grid-cols-[minmax(0,5.9rem)_minmax(0,1fr)_3.3rem]"
    : "grid grid-cols-1";
  const rowControlShellClass =
    "grid grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center divide-x divide-slate-200 border-t border-slate-200 bg-slate-50";
  const cardPaddingClass = largePrint ? "p-2" : "p-3";
  const cardOverflowClass = largePrint ? "overflow-visible" : "overflow-hidden";
  const formSpacingClass = largePrint ? "space-y-1.5" : "space-y-3";
  const boardWidthClass = largePrint ? "max-w-full" : "max-w-[15.25rem]";
  const boardGapClass = largePrint ? "gap-1.5" : "gap-1.5";
  const boardFrameClass = largePrint
    ? "wordle-board-window h-[9.15rem] overflow-hidden rounded-md px-0.5 py-1.5"
    : "";
  const boardRowsKey = largePrint ? `visible-row-${visibleStartRowIndex}` : "all-rows";
  const boardRowsClass = largePrint ? "wordle-board-rows-replace" : "";
  const tileClass = largePrint ? "wordle-tile--large" : "";
  const keyboardSpacingClass = largePrint ? "wordle-keyboard wordle-keyboard--large" : "wordle-keyboard";
  const keyboardRowGapClass = largePrint ? "gap-1" : "gap-1.5";
  const keyboardMiddleRowPaddingClass = largePrint ? "px-2" : "px-3";
  const keyClass = largePrint ? "wordle-key--large" : "";
  const actionKeyClass = largePrint ? "wordle-key--large" : "";
  const validationClass = largePrint ? "min-h-1 text-xs leading-none" : "min-h-5 text-sm";
  const messageClass = largePrint ? "text-base" : "text-sm";
  const definitionEyebrowClass = largePrint ? "text-xs" : "text-[0.68rem]";
  const nextLevel = Math.min(maxWordleLevel, (state?.game.difficulty ?? 1) + 1);
  const answerText = state?.result.answer?.toUpperCase() ?? "";
  const showWinDialog = gameStatus === "won" && !winDialogDismissed && !isAnimatingReveal;
  const showLossDialog =
    gameStatus === "lost" && answerText.length > 0 && !lossDialogDismissed && !isAnimatingReveal;
  const winGuessLabel = state?.result.attemptsUsed === 1 ? "guess" : "guesses";
  const winSummaryText =
    state?.result.status === "won"
      ? `Solved in ${state.result.attemptsUsed} ${winGuessLabel}`
      : "";
  const lossGuessLabel = state?.result.attemptsUsed === 1 ? "guess" : "guesses";
  const lossSummaryText =
    state?.result.status === "lost"
      ? `Out of guesses after ${state.result.attemptsUsed} ${lossGuessLabel}. The correct word was ${answerText}.`
      : "";

  return (
    <section className="page-fade wordle-game" aria-label="Wordle game" data-large-print={largePrint}>
      <details className="mb-3 rounded-xl border border-slate-200 bg-white p-3 text-sm"><summary className="cursor-pointer font-bold saints-focus">How to play Wordle</summary><p className="mt-2 leading-relaxed">Find the five-letter word in six guesses. ✓ means the right letter in the right place; ↔ means the letter belongs elsewhere; × means it is absent, or you have already found all copies of that letter. There is no timer. Your Wordle level measures mastery, separately from weekly league points.</p></details>
      <section className={["max-w-full rounded-lg saints-card wordle-game-card", cardOverflowClass, cardPaddingClass].join(" ")}>
        <form className={formSpacingClass} onSubmit={handleSubmit}>
          <div className="space-y-2">
            {statusText && !isAnimatingReveal && !showWinDialog && !showLossDialog ? (
              <p className={["text-center font-black text-slate-700", statusTextClass].join(" ")}>
                {statusText}
              </p>
            ) : null}

            <div className={controlBarClass} aria-label="Wordle settings">
              <div className={settingsRowClass}>
                {state ? (
                  <div
                    className={[
                      "flex min-h-[3.3rem] min-w-0 items-center gap-1.5 bg-white px-2 py-2",
                      state.game.difficulty <= 5 ? "text-emerald-800" : "",
                      state.game.difficulty > 5 && state.game.difficulty <= 10 ? "text-sky-800" : "",
                      state.game.difficulty > 10 && state.game.difficulty <= 15 ? "text-amber-800" : "",
                      state.game.difficulty > 15 ? "text-rose-800" : "",
                    ].join(" ")}
                  >
                    <span className="min-w-0">
                      <span className="block text-[0.62rem] font-black uppercase leading-none tracking-normal text-slate-500">
                        Level
                      </span>
                      <span className="mt-1 block text-2xl font-black leading-none">
                        {state.game.difficulty}
                      </span>
                    </span>
                  </div>
                ) : null}

                <button
                  type="button"
                  onClick={() => setLargePrint((current) => !current)}
                  aria-pressed={largePrint}
                  aria-label={largePrint ? "Use standard text size" : "Use large text size"}
                  data-testid="wordle-text-size-toggle"
                  className="flex min-h-[3.3rem] min-w-0 items-center justify-center bg-white px-2 py-2 text-slate-950 transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-saints-red/15"
                >
                  <span className="sr-only">{largePrint ? "Large text selected" : "Standard text selected"}</span>
                  <span
                    className="inline-flex h-10 min-w-[4.75rem] shrink-0 items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-2 shadow-sm ring-1 ring-slate-700"
                    aria-hidden="true"
                  >
                    <span
                      className={[
                        "flex h-6 w-6 items-center justify-center rounded-lg text-base font-black leading-none transition",
                        largePrint ? "text-slate-400" : "bg-white text-slate-950 shadow-sm",
                      ].join(" ")}
                    >
                      A
                    </span>
                    <span
                      className={[
                        "flex h-8 w-8 items-center justify-center rounded-lg text-[1.5rem] font-black leading-none transition",
                        largePrint ? "bg-saints-red text-white shadow-sm" : "text-slate-300",
                      ].join(" ")}
                    >
                      A
                    </span>
                  </span>
                </button>

                <button
                  type="button"
                  onClick={handleSoundToggle}
                  aria-pressed={soundEnabled}
                  aria-label={soundEnabled ? "Turn Wordle sound off" : "Turn Wordle sound on"}
                  className="flex min-h-[3.3rem] min-w-0 items-center justify-center bg-white px-2 py-2 text-slate-700 transition hover:bg-slate-50 hover:text-saints-red focus:outline-none focus:ring-4 focus:ring-saints-red/15"
                >
                  {soundEnabled ? (
                    <Volume2 aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  ) : (
                    <VolumeX aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  )}
                </button>
              </div>

              {largePrint ? (
                <div className={rowControlShellClass} aria-label="Guess row controls">
                  <button
                    type="button"
                    onClick={() => handleRowControlClick(-1)}
                    disabled={!rowScrollState.canScrollUp}
                    aria-label="Show previous guess row"
                    className={rowControlButtonClass}
                  >
                    <ChevronUp aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
                  </button>
                  <span className="text-center text-[0.68rem] font-black uppercase tracking-normal text-slate-600">
                    Board rows
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRowControlClick(1)}
                    disabled={!rowScrollState.canScrollDown}
                    aria-label="Show next guess row"
                    className={rowControlButtonClass}
                  >
                    <ChevronDown aria-hidden="true" className="h-6 w-6" strokeWidth={3} />
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <div
            ref={boardScrollRef}
            onWheel={handleBoardWheel}
            onTouchStart={handleBoardTouchStart}
            onTouchMove={handleBoardTouchMove}
            onTouchEnd={handleBoardTouchEnd}
            onTouchCancel={handleBoardTouchEnd}
            className={[
              "mx-auto w-full",
              boardFrameClass,
              boardWidthClass,
            ].join(" ")}
            style={largePrint && largeBoardWindowHeight !== null ? { height: `${largeBoardWindowHeight}px` } : undefined}
            aria-label="Wordle board"
            data-testid="wordle-board-scroll"
          >
            <div key={boardRowsKey} className={["grid", boardGapClass, boardRowsClass].join(" ")}>
              {visibleRowIndexes.map((rowIndex) => {
                const submittedGuess = guesses[rowIndex];
                const isDraftRow = submittedGuess === undefined && rowIndex === guesses.length;
                const isRevealingRow = revealingRowIndex === rowIndex;
                const draft = isDraftRow && !isComplete ? guess.toUpperCase() : "";

                return (
                  <div
                    key={rowIndex}
                    data-wordle-row={rowIndex}
                    data-active-row={rowIndex === activeRowIndex}
                    className={["grid wordle-board-row", boardGapClass].join(" ")}
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
                          : "wordle-tile--empty";
                      const isLatestReveal =
                        isRevealingRow && shouldShowFeedback && letterIndex === revealedLetters - 1;

                      return (
                        <div
                          key={letterIndex}
                          role="img"
                          aria-label={`Guess ${rowIndex + 1}, position ${letterIndex + 1}: ${letter || "empty"}${shouldShowFeedback && feedbackTile ? `, ${feedbackTile.color === "green" ? "correct position" : feedbackTile.color === "yellow" ? "different position" : "absent or no further copies"}` : ""}`}
                          data-score={shouldShowFeedback && feedbackTile ? (feedbackTile.color === "green" ? "✓" : feedbackTile.color === "yellow" ? "↔" : "×") : undefined}
                          className={[
                            "wordle-tile",
                            tileClass,
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
          </div>

          <div aria-live="polite" className={["text-center font-black", validationClass].join(" ")}>
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

          <div className={keyboardSpacingClass} aria-label="Wordle keyboard">
            {keyboardRows.map((row, rowIndex) => (
              <div
                key={row}
                className={[
                  "grid",
                  keyboardRowGapClass,
                  rowIndex === 1
                    ? ["grid-cols-9", keyboardMiddleRowPaddingClass].join(" ")
                    : rowIndex === 2
                      ? "grid-cols-[1.35fr_repeat(7,1fr)_1.35fr]"
                      : "grid-cols-10",
                ].join(" ")}
              >
                {rowIndex === 2 ? (
                  <button
                    type="button"
                    onClick={() => void submitGuess()}
                    disabled={!canSubmit}
                    className={[
                      "wordle-key wordle-key--action wordle-key--enter",
                      actionKeyClass,
                    ].join(" ")}
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
                        keyClass,
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
                    className={[
                      "wordle-key wordle-key--action",
                      actionKeyClass,
                    ].join(" ")}
                  >
                    <Delete aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </button>
                ) : null}
              </div>
            ))}
          </div>

          {error ? (
            <p className={["rounded-2xl bg-red-50 px-3 py-2 text-center font-bold text-saints-red", messageClass].join(" ")}>
              {error}
            </p>
          ) : null}
        </form>

        {isComplete && state ? <SavedWordleStats state={state} /> : null}

        {isComplete ? (
          <section
            className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3"
            aria-label="Word definition"
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <p className={["font-black uppercase tracking-normal text-saints-red", definitionEyebrowClass].join(" ")}>
                Today's word
              </p>
              {state ? (
                <span
                  className={[
                    "inline-flex items-center rounded-full px-2.5 py-1 font-black uppercase tracking-normal",
                    definitionEyebrowClass,
                    difficultyBadgeClasses(state.game.difficulty),
                  ].join(" ")}
                >
                  Difficulty {state.game.difficulty}
                </span>
              ) : null}
            </div>
            <DictionaryDefinitionCard
              definition={definition}
              error={definitionError}
              loading={definitionLoading}
              largePrint={largePrint}
            />
          </section>
        ) : null}
      </section>

      <p className="mt-3 text-center text-sm font-bold">{isComplete ? `${guesses.length} guesses played` : `Guess ${Math.min(guesses.length + 1, maxAttempts)} of ${maxAttempts}`}</p>
      <p className="sr-only" aria-live="polite" aria-atomic="true">{!isAnimatingReveal && guesses.length ? guesses[guesses.length - 1].feedback.map((tile, index) => `Position ${index + 1}: ${tile.letter}, ${tile.color === "green" ? "correct position" : tile.color === "yellow" ? "different position" : "absent or no further copies"}`).join(". ") : ""}</p>
      {largePrint && guesses.length > 0 && !isAnimatingReveal ? <details className="mt-3 rounded-xl border border-slate-200 bg-white p-3"><summary className="cursor-pointer font-bold saints-focus">All previous guesses ({guesses.length})</summary><div className="mt-3 space-y-3">{guesses.map((row, index) => <div key={row.attemptNumber}><p className="mb-1 text-sm font-bold">Guess {index + 1}</p><div className="grid grid-cols-5 gap-1">{row.feedback.map((tile, position) => <div key={position} className={`rounded-lg border p-2 text-center text-xl font-black ${tile.color === "green" ? "bg-emerald-100" : tile.color === "yellow" ? "bg-amber-100" : "bg-slate-100"}`}><span>{tile.letter.toUpperCase()}</span><span className="block text-base" aria-label={tile.color === "green" ? "correct position" : tile.color === "yellow" ? "different position" : "absent or no further copies"}>{tile.color === "green" ? "✓" : tile.color === "yellow" ? "↔" : "×"}</span></div>)}</div></div>)}</div></details> : null}
      {isComplete && !isAnimatingReveal && state ? <DailyJourney current="wordle" summary={`Fulton's Quiz · ${state.game.date}\nWordle ${state.result.status === "won" ? `${state.result.attemptsUsed}/6` : "X/6"} · ${state.result.score} game points\n${guesses.map(row => row.feedback.map(tile => tile.color === "green" ? "🟩" : tile.color === "yellow" ? "🟨" : "⬛").join("")).join("\n")}`} /> : null}

      {showWinDialog ? <DialogPortal onClose={() => setWinDialogDismissed(true)}>
        <div
          className="fixed inset-0 z-[80] flex items-start justify-center bg-saints-black/75 px-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-12 min-[540px]:items-center min-[540px]:pt-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wordle-win-title"
          aria-describedby="wordle-win-description"
        >
          <section className="wordle-win-modal max-h-[calc(100dvh_-_8.5rem_-_env(safe-area-inset-bottom))] w-full max-w-[350px] overflow-y-auto rounded-lg bg-white text-slate-950 shadow-2xl min-[540px]:max-h-[calc(100dvh_-_7rem_-_env(safe-area-inset-bottom))]">
            <div className="relative p-3">
              <button
                type="button"
                onClick={() => setWinDialogDismissed(true)}
                aria-label="Close win message"
                className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-700 transition hover:bg-slate-200 focus:outline-none focus:ring-4 focus:ring-saints-red/15"
              >
                <X aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              </button>

              <div className="pr-9 text-left">
                <div className="flex items-center gap-2.5">
                  <div className="wordle-win-badge flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-white shadow-lg shadow-emerald-900/20">
                    <Trophy aria-hidden="true" className="h-5 w-5" strokeWidth={2.5} />
                  </div>
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-emerald-700">
                    Correct guess
                  </p>
                </div>
                <h2 id="wordle-win-title" className="mt-2 text-[1.55rem] font-black leading-none text-slate-950">
                  Congratulations
                </h2>
                <p id="wordle-win-description" className="sr-only">
                  {winSummaryText}. {state?.result.score ?? 0} points earned. Next level {nextLevel}.
                </p>
              </div>

              <dl className="mt-3 grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-slate-50 px-2.5 py-2 ring-1 ring-slate-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-slate-500">
                    Solved
                  </dt>
                  <dd className="mt-1 whitespace-nowrap text-base font-black leading-tight text-slate-950">
                    {state?.result.attemptsUsed} {winGuessLabel}
                  </dd>
                </div>
                <div className="rounded-lg bg-emerald-50 px-2.5 py-2 ring-1 ring-emerald-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-emerald-700">
                    Points
                  </dt>
                  <dd className="mt-1 text-lg font-black leading-tight text-slate-950">
                    +{state?.result.score ?? 0}
                  </dd>
                </div>
                <div className="rounded-lg bg-saints-redSoft px-2.5 py-2 ring-1 ring-red-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-saints-red">
                    Next level
                  </dt>
                  <dd className="mt-1 text-lg font-black leading-tight text-slate-950">{nextLevel}</dd>
                </div>
              </dl>

              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                    Today's word
                  </p>
                  {state ? (
                    <span
                      className={[
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[0.68rem] font-black uppercase tracking-normal",
                        difficultyBadgeClasses(state.game.difficulty),
                      ].join(" ")}
                    >
                      Level {state.game.difficulty}
                    </span>
                  ) : null}
                </div>
                <DictionaryDefinitionCard
                  compact
                  definition={definition}
                  error={definitionError}
                  loading={definitionLoading}
                  largePrint={largePrint}
                />
              </div>
            </div>
          </section>
        </div>
      </DialogPortal> : null}

      {showLossDialog ? <DialogPortal onClose={() => setLossDialogDismissed(true)}>
        <div
          className="fixed inset-0 z-[80] flex items-start justify-center bg-saints-black/75 px-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-12 min-[540px]:items-center min-[540px]:pt-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wordle-loss-title"
          aria-describedby="wordle-loss-description"
        >
          <section className="wordle-win-modal max-h-[calc(100dvh_-_8.5rem_-_env(safe-area-inset-bottom))] w-full max-w-[350px] overflow-y-auto rounded-lg bg-white text-slate-950 shadow-2xl min-[540px]:max-h-[calc(100dvh_-_7rem_-_env(safe-area-inset-bottom))]">
            <div className="relative p-3">
              <button
                type="button"
                onClick={() => setLossDialogDismissed(true)}
                aria-label="Close answer message"
                className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-700 transition hover:bg-slate-200 focus:outline-none focus:ring-4 focus:ring-saints-red/15"
              >
                <X aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
              </button>

              <div className="pr-9 text-left">
                <div className="flex items-center gap-2.5">
                  <div className="wordle-win-badge flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-red text-white shadow-lg shadow-red-900/20">
                    <CircleAlert aria-hidden="true" className="h-5 w-5" strokeWidth={2.5} />
                  </div>
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                    Out of guesses
                  </p>
                </div>
                <h2 id="wordle-loss-title" className="mt-2 text-[1.55rem] font-black leading-none text-slate-950">
                  The word was {answerText}
                </h2>
                <p id="wordle-loss-description" className="sr-only">
                  {lossSummaryText} No points earned.
                </p>
              </div>

              <dl className="mt-3 grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-slate-50 px-2.5 py-2 ring-1 ring-slate-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-slate-500">
                    Guesses
                  </dt>
                  <dd className="mt-1 whitespace-nowrap text-base font-black leading-tight text-slate-950">
                    {state?.result.attemptsUsed} {lossGuessLabel}
                  </dd>
                </div>
                <div className="rounded-lg bg-slate-50 px-2.5 py-2 ring-1 ring-slate-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-slate-500">
                    Points
                  </dt>
                  <dd className="mt-1 text-lg font-black leading-tight text-slate-950">
                    {state?.result.score ?? 0}
                  </dd>
                </div>
                <div className="rounded-lg bg-saints-redSoft px-2.5 py-2 ring-1 ring-red-200">
                  <dt className="text-[0.65rem] font-black uppercase tracking-normal text-saints-red">
                    Correct word
                  </dt>
                  <dd className="mt-1 text-lg font-black leading-tight text-slate-950">{answerText}</dd>
                </div>
              </dl>

              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                    Today's word
                  </p>
                  {state ? (
                    <span
                      className={[
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[0.68rem] font-black uppercase tracking-normal",
                        difficultyBadgeClasses(state.game.difficulty),
                      ].join(" ")}
                    >
                      Level {state.game.difficulty}
                    </span>
                  ) : null}
                </div>
                <DictionaryDefinitionCard
                  compact
                  definition={definition}
                  error={definitionError}
                  loading={definitionLoading}
                  largePrint={largePrint}
                />
              </div>
            </div>
          </section>
        </div>
      </DialogPortal> : null}
    </section>
  );
}
