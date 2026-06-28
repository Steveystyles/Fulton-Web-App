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
  Delete,
  ExternalLink,
  Hash,
  LoaderCircle,
  Trophy,
  Type,
  X,
} from "lucide-react";
import { api, type FeedbackColor, type WordleState } from "../lib/api";
import type { WordleDefinition } from "../lib/api";

type GuessValidity = "empty" | "short" | "checking" | "valid" | "invalid";

const keyboardRows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
const largePrintStorageKey = "fultons-wordle-large-print";
const maxWordleLevel = 20;

const colorPriority: Record<FeedbackColor, number> = {
  grey: 1,
  yellow: 2,
  green: 3,
};

const tileColors: Record<FeedbackColor, string> = {
  green: "border-emerald-700 bg-emerald-700 text-white",
  yellow: "border-amber-300 bg-amber-300 text-slate-950",
  grey: "border-slate-700 bg-slate-700 text-white",
};

const keyboardColors: Record<FeedbackColor, string> = {
  green: "bg-emerald-700 text-white",
  yellow: "bg-amber-300 text-slate-950",
  grey: "bg-slate-700 text-white",
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
  const visibleDefinitions = definitionItems.slice(0, compact ? 2 : 3);
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

export function Wordle() {
  const boardScrollRef = useRef<HTMLDivElement | null>(null);
  const wheelGestureLockedRef = useRef(false);
  const wheelUnlockTimeoutRef = useRef<number | null>(null);
  const touchStartYRef = useRef<number | null>(null);
  const touchGestureHandledRef = useRef(false);
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
  const [winDialogDismissed, setWinDialogDismissed] = useState(false);
  const [rowScrollState, setRowScrollState] = useState({
    canScrollDown: false,
    canScrollUp: false,
  });

  const gameStatus = state?.result.status ?? "in_progress";
  const isComplete = gameStatus !== "in_progress";
  const wordLength = state?.game.wordLength ?? 5;
  const maxAttempts = state?.game.maxAttempts ?? 6;
  const guesses = state?.result.guesses ?? [];
  const activeRowIndex = isComplete
    ? Math.max(0, guesses.length - 1)
    : Math.min(guesses.length, maxAttempts - 1);
  const visibleStartRowIndex = largePrint
    ? Math.max(0, activeRowIndex - 1)
    : 0;
  const canSubmit = state !== null && !isComplete && guessValidity === "valid" && !submitting;

  useEffect(() => {
    writeLargePrintPreference(largePrint);
  }, [largePrint]);

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
    if (!largePrint) {
      return;
    }

    const board = boardScrollRef.current;
    const row = board?.querySelector<HTMLElement>(
      `[data-wordle-row="${visibleStartRowIndex}"]`,
    );
    if (board !== null && row !== undefined && row !== null) {
      board.scrollTo({ top: row.offsetTop, behavior: "smooth" });
    }
  }, [largePrint, visibleStartRowIndex]);

  const addLetter = useCallback(
    (letter: string) => {
      if (isComplete || submitting) {
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
    [isComplete, submitting, wordLength],
  );

  const removeLetter = useCallback(() => {
    if (isComplete || submitting) {
      return;
    }
    setError("");
    setGuess((currentGuess) => currentGuess.slice(0, -1));
  }, [isComplete, submitting]);

  const submitGuess = useCallback(async () => {
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
  }, [canSubmit, guess, guessValidity, state, wordLength]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      if (tagName === "INPUT" || tagName === "TEXTAREA" || target?.isContentEditable) {
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

  const keyboardState = useMemo(() => {
    const statuses = new Map<string, FeedbackColor>();

    for (const submittedGuess of guesses) {
      for (const tile of submittedGuess.feedback) {
        const previous = statuses.get(tile.letter);
        if (previous === undefined || colorPriority[tile.color] > colorPriority[previous]) {
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
      const guessLabel = state.result.attemptsUsed === 1 ? "guess" : "guesses";
      return `Solved in ${state.result.attemptsUsed} ${guessLabel} - ${state.result.score} pts`;
    }

    if (state.result.status === "lost") {
      return `Answer: ${state.result.answer?.toUpperCase()}`;
    }

    return "";
  }, [loading, state]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitGuess();
  }

  const updateBoardScrollControls = useCallback(
    (board: HTMLDivElement | null = boardScrollRef.current) => {
      if (!largePrint || board === null) {
        setRowScrollState((currentState) =>
          currentState.canScrollDown || currentState.canScrollUp
            ? { canScrollDown: false, canScrollUp: false }
            : currentState,
        );
        return;
      }

      const maxScrollTop = Math.max(0, board.scrollHeight - board.clientHeight);
      const nextState = {
        canScrollDown: board.scrollTop < maxScrollTop - 1,
        canScrollUp: board.scrollTop > 1,
      };
      setRowScrollState((currentState) =>
        currentState.canScrollDown === nextState.canScrollDown &&
        currentState.canScrollUp === nextState.canScrollUp
          ? currentState
          : nextState,
      );
    },
    [largePrint],
  );

  const scrollBoardByRow = useCallback((board: HTMLDivElement, direction: 1 | -1) => {
    const row = board.querySelector<HTMLElement>("[data-wordle-row]");
    const rowGroup = board.firstElementChild;
    if (row === null || rowGroup === null) {
      return;
    }

    const rowGap = Number.parseFloat(window.getComputedStyle(rowGroup).rowGap || "0") || 0;
    const rowStep = row.getBoundingClientRect().height + rowGap;
    if (rowStep <= 0) {
      return;
    }

    const currentIndex = Math.round(board.scrollTop / rowStep);
    const maxScrollTop = Math.max(0, board.scrollHeight - board.clientHeight);
    const nextTop = Math.min(
      maxScrollTop,
      Math.max(0, (currentIndex + direction) * rowStep),
    );
    board.scrollTo({ top: nextTop, behavior: "smooth" });
    window.setTimeout(() => updateBoardScrollControls(board), 320);
  }, [updateBoardScrollControls]);

  useEffect(() => {
    updateBoardScrollControls();
  }, [largePrint, maxAttempts, updateBoardScrollControls, visibleStartRowIndex]);

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

      event.preventDefault();
      releaseWheelGestureAfterBurst();
      if (wheelGestureLockedRef.current) {
        return;
      }

      wheelGestureLockedRef.current = true;
      scrollBoardByRow(event.currentTarget, event.deltaY > 0 ? 1 : -1);
    },
    [largePrint, releaseWheelGestureAfterBurst, scrollBoardByRow],
  );

  const handleBoardScroll = useCallback(() => {
    updateBoardScrollControls();
  }, [updateBoardScrollControls]);

  const handleRowControlClick = useCallback(
    (direction: 1 | -1) => {
      if (!largePrint || boardScrollRef.current === null) {
        return;
      }

      scrollBoardByRow(boardScrollRef.current, direction);
    },
    [largePrint, scrollBoardByRow],
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
      scrollBoardByRow(event.currentTarget, deltaY > 0 ? 1 : -1);
    },
    [largePrint, scrollBoardByRow],
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
  const rowControlShellClass =
    "grid grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center divide-x divide-slate-200 border-t border-slate-200 bg-slate-50";
  const switchTrackClass = largePrint ? "bg-saints-red" : "bg-slate-300";
  const switchThumbClass = largePrint ? "translate-x-4" : "translate-x-0";
  const cardPaddingClass = largePrint ? "p-2" : "p-3";
  const formSpacingClass = largePrint ? "space-y-2.5" : "space-y-3";
  const boardWidthClass = largePrint ? "max-w-full" : "max-w-[17.5rem]";
  const boardGapClass = largePrint ? "gap-1.5" : "gap-1.5";
  const boardFrameClass = largePrint
    ? "wordle-board-window aspect-[2.56/1] overflow-y-auto overflow-x-hidden overscroll-contain rounded-md"
    : "";
  const boardRowsKey = largePrint ? `visible-row-${visibleStartRowIndex}` : "all-rows";
  const boardRowsClass = largePrint ? "wordle-board-rows-replace" : "";
  const tileClass = largePrint
    ? "w-full text-[2.7rem] min-[380px]:text-[2.9rem]"
    : "w-full text-[1.7rem] min-[380px]:text-[1.95rem]";
  const keyboardSpacingClass = largePrint ? "space-y-1.5" : "space-y-1.5";
  const keyboardRowGapClass = largePrint ? "gap-1.5" : "gap-1.5";
  const keyboardMiddleRowPaddingClass = largePrint ? "px-2" : "px-3";
  const keyClass = largePrint
    ? "min-h-[3.35rem] text-[1.08rem] min-[380px]:min-h-[3.55rem] min-[380px]:text-[1.16rem]"
    : "min-h-10 text-[0.8rem] min-[380px]:min-h-[2.9rem]";
  const actionKeyClass = largePrint
    ? "min-h-[3.35rem] text-[0.9rem] min-[380px]:min-h-[3.55rem] min-[380px]:text-[0.94rem]"
    : "min-h-10 text-[0.72rem] min-[380px]:min-h-[2.9rem]";
  const validationClass = largePrint ? "min-h-6 text-base" : "min-h-5 text-sm";
  const messageClass = largePrint ? "text-base" : "text-sm";
  const definitionEyebrowClass = largePrint ? "text-xs" : "text-[0.68rem]";
  const nextLevel = Math.min(maxWordleLevel, (state?.game.difficulty ?? 1) + 1);
  const showWinDialog = gameStatus === "won" && !winDialogDismissed;
  const winGuessLabel = state?.result.attemptsUsed === 1 ? "guess" : "guesses";
  const winSummaryText =
    state?.result.status === "won"
      ? `Solved in ${state.result.attemptsUsed} ${winGuessLabel}`
      : "";

  return (
    <section className="page-fade" aria-label="Wordle game" data-large-print={largePrint}>
      <section className={["max-w-full overflow-hidden rounded-lg saints-card", cardPaddingClass].join(" ")}>
        <form className={formSpacingClass} onSubmit={handleSubmit}>
          <div className="space-y-2">
            {statusText ? (
              <p className={["text-center font-black text-slate-700", statusTextClass].join(" ")}>
                {statusText}
              </p>
            ) : null}

            <div className={controlBarClass} aria-label="Wordle settings">
              <div className="grid grid-cols-2 divide-x divide-slate-200">
                {state ? (
                  <div
                    className={[
                      "flex min-h-[3.3rem] min-w-0 items-center gap-2 bg-white px-3 py-2",
                      state.game.difficulty <= 5 ? "text-emerald-800" : "",
                      state.game.difficulty > 5 && state.game.difficulty <= 10 ? "text-sky-800" : "",
                      state.game.difficulty > 10 && state.game.difficulty <= 15 ? "text-amber-800" : "",
                      state.game.difficulty > 15 ? "text-rose-800" : "",
                    ].join(" ")}
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
                      <Hash aria-hidden="true" className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[0.62rem] font-black uppercase leading-none tracking-normal text-slate-500">
                        Difficulty
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
                  className="flex min-h-[3.3rem] min-w-0 items-center justify-between gap-2 bg-white px-3 py-2 text-left text-slate-950 transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-saints-red/15"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-saints-redSoft text-saints-red ring-1 ring-red-100">
                      <Type aria-hidden="true" className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 whitespace-nowrap text-xs font-black uppercase leading-tight tracking-normal text-slate-700">
                      Large text
                    </span>
                  </span>
                  <span
                    className={[
                      "relative h-5 w-9 shrink-0 rounded-full p-0.5 transition",
                      switchTrackClass,
                    ].join(" ")}
                    aria-hidden="true"
                  >
                    <span
                      className={[
                        "block h-4 w-4 rounded-full bg-white shadow-sm transition",
                        switchThumbClass,
                      ].join(" ")}
                    />
                  </span>
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
                    <ChevronUp aria-hidden="true" className="h-4 w-4" strokeWidth={3} />
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
                    <ChevronDown aria-hidden="true" className="h-4 w-4" strokeWidth={3} />
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <div
            ref={boardScrollRef}
            onScroll={handleBoardScroll}
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
            aria-label="Wordle board"
            data-testid="wordle-board-scroll"
          >
            <div key={boardRowsKey} className={["grid", boardGapClass, boardRowsClass].join(" ")}>
              {Array.from({ length: maxAttempts }, (_, rowIndex) => {
                const submittedGuess = guesses[rowIndex];
                const isDraftRow = submittedGuess === undefined && rowIndex === guesses.length;
                const draft = isDraftRow && !isComplete ? guess.toUpperCase() : "";

                return (
                  <div
                    key={rowIndex}
                    data-wordle-row={rowIndex}
                    data-active-row={rowIndex === activeRowIndex}
                    className={["grid", boardGapClass].join(" ")}
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
                            "flex aspect-square items-center justify-center rounded-md border-2 font-black uppercase leading-none shadow-sm",
                            tileClass,
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
          </div>

          <div aria-live="polite" className={["text-center font-black", validationClass].join(" ")}>
            {guessValidity === "checking" ? (
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
                      "flex items-center justify-center rounded-md bg-saints-red px-1 font-black uppercase text-white transition disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500",
                      actionKeyClass,
                    ].join(" ")}
                  >
                    Enter
                  </button>
                ) : null}

                {row.split("").map((letter) => {
                  const status = keyboardState.get(letter);
                  const colorClass =
                    status === undefined ? "bg-slate-100 text-slate-950" : keyboardColors[status];

                  return (
                    <button
                      key={letter}
                      type="button"
                      onClick={() => addLetter(letter)}
                      disabled={isComplete || submitting}
                      className={[
                        "flex items-center justify-center rounded-md font-black uppercase shadow-sm transition focus:outline-none focus:ring-2 focus:ring-saints-red/30 disabled:cursor-not-allowed",
                        keyClass,
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
                    className={[
                      "flex items-center justify-center rounded-md bg-slate-100 text-slate-950 shadow-sm transition focus:outline-none focus:ring-2 focus:ring-saints-red/30 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400",
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

      {showWinDialog ? (
        <div
          className="fixed inset-0 z-[80] flex items-start justify-center bg-saints-black/75 px-4 pb-[calc(5.75rem+env(safe-area-inset-bottom))] pt-20 min-[540px]:items-center min-[540px]:pt-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wordle-win-title"
          aria-describedby="wordle-win-description"
        >
          <section className="wordle-win-modal max-h-[calc(100dvh_-_10.75rem_-_env(safe-area-inset-bottom))] w-full max-w-[360px] overflow-y-auto rounded-lg bg-white text-slate-950 shadow-2xl min-[540px]:max-h-[calc(100dvh_-_7rem_-_env(safe-area-inset-bottom))]">
            <div className="relative px-4 pb-4 pt-5 text-center">
              <button
                type="button"
                onClick={() => setWinDialogDismissed(true)}
                aria-label="Close win message"
                className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-700 transition hover:bg-slate-200 focus:outline-none focus:ring-4 focus:ring-saints-red/15"
              >
                <X aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
              </button>
              <div className="wordle-win-badge mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-700 text-white shadow-lg shadow-emerald-900/20">
                <Trophy aria-hidden="true" className="h-7 w-7" strokeWidth={2.5} />
              </div>
              <p className="mt-3 text-[0.68rem] font-black uppercase tracking-normal text-emerald-700">
                Correct guess
              </p>
              <h2 id="wordle-win-title" className="mt-1 text-[1.65rem] font-black leading-tight text-slate-950">
                Congratulations
              </h2>
              <p id="wordle-win-description" className="mt-1 text-sm font-bold text-slate-500">
                {winSummaryText}
              </p>
            </div>

            <dl className="grid grid-cols-2 gap-2 px-4 pb-4">
              <div className="flex min-h-[5.25rem] flex-col justify-center rounded-lg bg-emerald-50 px-3 py-3 text-center ring-1 ring-emerald-200">
                <dt className="text-[0.68rem] font-black uppercase tracking-normal text-emerald-700">
                  Score
                </dt>
                <dd className="mt-1 text-2xl font-black leading-none text-emerald-900">{state?.result.score ?? 0}</dd>
                <dd className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-emerald-700">
                  points
                </dd>
              </div>
              <div className="flex min-h-[5.25rem] flex-col justify-center rounded-lg bg-saints-redSoft px-3 py-3 text-center ring-1 ring-red-200">
                <dt className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                  Next level
                </dt>
                <dd className="mt-1 text-2xl font-black leading-none text-slate-950">{nextLevel}</dd>
              </div>
            </dl>

            <div className="px-4 pb-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="mb-3 flex items-center justify-between gap-2">
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
      ) : null}
    </section>
  );
}
