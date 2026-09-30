import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Check,
  CalendarDays,
  CircleHelp,
  Gauge,
  Gift,
  Hash,
  Info,
  LoaderCircle,
  MapPinned,
  Medal,
  RefreshCw,
  Star,
  TrendingUp,
  Trophy,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Card } from "../components/Card";
import { useAuth } from "../context/AuthContext";
import { api, type LeaderboardPlayer, type LeaderboardResponse } from "../lib/api";

function percent(value: number, maximum: number) {
  if (maximum <= 0 || value <= 0) {
    return "0%";
  }
  return `${Math.max(4, Math.round((value / maximum) * 100))}%`;
}

function shortDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
  }).format(new Date(year, month - 1, day));
}

function quizAccuracy(player: LeaderboardPlayer) {
  const answered = player.quizPlayed * 3;
  return answered > 0 ? `${Math.round((player.quizCorrect / answered) * 100)}%` : "0%";
}

function rankLabel(player: LeaderboardPlayer) {
  return player.weeklyPoints > 0 ? `#${player.rank}` : "—";
}

const QUIZ_JOURNEY = [
  {
    label: "Easy",
    value: "1 pt",
    icon: Check,
    ringClass: "border-emerald-200 text-emerald-500",
  },
  {
    label: "Medium",
    value: "3 pts",
    icon: Check,
    ringClass: "border-amber-200 text-amber-500",
  },
  {
    label: "Hard",
    value: "5 pts",
    icon: Check,
    ringClass: "border-rose-200 text-rose-500",
  },
  {
    label: "Perfect round",
    value: "+3 pts",
    icon: Star,
    ringClass: "border-rose-200 text-saints-red",
    valueClassName: "text-saints-red",
  },
] as const;

const WORDLE_JOURNEY = [
  {
    value: 10,
    accentClass: "border-rose-200 text-rose-500",
    lineClass: "bg-rose-200",
    arrowClass: "text-rose-300",
  },
  {
    value: 5,
    accentClass: "border-orange-200 text-orange-500",
    lineClass: "bg-orange-200",
    arrowClass: "text-orange-300",
  },
  {
    value: 4,
    accentClass: "border-amber-200 text-amber-500",
    lineClass: "bg-amber-200",
    arrowClass: "text-amber-300",
  },
  {
    value: 3,
    accentClass: "border-lime-200 text-lime-500",
    lineClass: "bg-lime-200",
    arrowClass: "text-lime-300",
  },
  {
    value: 2,
    accentClass: "border-emerald-200 text-emerald-500",
    lineClass: "bg-emerald-200",
    arrowClass: "text-emerald-300",
  },
  {
    value: 1,
    accentClass: "border-teal-200 text-teal-500",
    lineClass: "bg-teal-200",
    arrowClass: "text-teal-300",
  },
] as const;

export function Leaderboard() {
  const { user } = useAuth();
  const [board, setBoard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const refreshInFlightRef = useRef(false);

  const loadScores = useCallback(async (initial = false) => {
    if (refreshInFlightRef.current) {
      return;
    }
    refreshInFlightRef.current = true;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError("");
    try {
      const response = await api.leaderboard();
      setBoard(response);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Scores failed to load.");
    } finally {
      refreshInFlightRef.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadScores(true);
  }, [loadScores]);

  const players = useMemo(() => {
    let previousPoints: number | null = null;
    let sharedRank = 0;
    return (board?.players ?? []).map((player, index) => {
      if (previousPoints === null || player.weeklyPoints !== previousPoints) {
        sharedRank = index + 1;
        previousPoints = player.weeklyPoints;
      }
      return player.rank === sharedRank ? player : { ...player, rank: sharedRank };
    });
  }, [board]);
  const selectedPlayer = useMemo(
    () => players.find((player) => player.id === selectedPlayerId) ?? null,
    [players, selectedPlayerId],
  );

  useEffect(() => {
    if (selectedPlayer === null) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedPlayerId(null);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedPlayer]);

  const currentPlayer = useMemo(
    () => players.find((player) => player.id === user?.id) ?? null,
    [players, user?.id],
  );
  const highestWeeklyScore = useMemo(
    () => players.reduce((highest, player) => Math.max(highest, player.weeklyPoints), 0),
    [players],
  );

  return (
    <section className="page-fade space-y-3 pb-2" aria-label="Scores">
      <Link
        to="/"
        className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-black text-slate-800 saints-focus"
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        Back to games
      </Link>
      {error && board !== null ? (
        <ScoresError
          message={error}
          onRetry={() => void loadScores()}
          retrying={refreshing}
        />
      ) : null}
      {loading && board === null ? (
        <Card>
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm font-black text-slate-500">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading scores
          </div>
        </Card>
      ) : error && board === null ? (
        <ScoresError
          message={error}
          onRetry={() => void loadScores(true)}
          retrying={loading}
        />
      ) : players.length === 0 ? (
        <Card>
          <p className="text-sm font-semibold leading-relaxed text-slate-600">
            No player scores yet.
          </p>
        </Card>
      ) : (
        <>
          {currentPlayer ? (
            <CurrentPlayerCard player={currentPlayer} highestWeeklyScore={highestWeeklyScore} />
          ) : null}

          <Card className="p-3">
            <div className="mb-3 flex flex-col gap-3 min-[430px]:flex-row min-[430px]:items-start min-[430px]:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-black text-slate-950">Rolling 7-day leaderboard</p>
                {board ? (
                  <p className="mt-0.5 flex items-start gap-1 text-xs font-bold leading-snug text-slate-500">
                    <CalendarDays aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    {shortDate(board.summary.periodStart)} - {shortDate(board.summary.periodEnd)} · tied totals share a rank
                  </p>
                ) : null}
              </div>
              {board ? (
                <div className="flex shrink-0 items-center gap-2 self-end min-[430px]:self-auto">
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                    {board.summary.playerCount} players
                  </span>
                  <button
                    type="button"
                    onClick={() => void loadScores()}
                    disabled={refreshing}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-black text-slate-700 transition hover:border-saints-red/40 hover:text-saints-red saints-focus disabled:cursor-wait disabled:text-slate-400"
                  >
                    <RefreshCw
                      aria-hidden="true"
                      className={["h-3.5 w-3.5", refreshing ? "animate-spin" : ""].join(" ")}
                    />
                    {refreshing ? "Refreshing" : "Refresh"}
                  </button>
                </div>
              ) : null}
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200">
              <table className="w-full border-collapse bg-white text-left" aria-label="Player score table">
                <thead className="bg-slate-50 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Player</th>
                    <th className="px-2 py-2 text-right">7-day pts</th>
                    <th className="px-3 py-2 text-right">Level</th>
                  </tr>
                </thead>
                <tbody>
                  {players.map((player) => (
                    <ScoreRow
                      key={player.id}
                      player={player}
                      isCurrentUser={player.id === user?.id}
                      onSelect={() => setSelectedPlayerId(player.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <ScoreGuide />
        </>
      )}

      <PlayerDetailDialog player={selectedPlayer} onClose={() => setSelectedPlayerId(null)} />
    </section>
  );
}

function ScoresError({
  message,
  onRetry,
  retrying,
}: {
  message: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <Card>
      <div className="flex flex-col gap-3 rounded-2xl bg-red-50 px-3 py-3 min-[380px]:flex-row min-[380px]:items-center min-[380px]:justify-between">
        <p className="text-sm font-bold text-saints-red">{message}</p>
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-saints-red px-3 text-sm font-black text-white transition hover:bg-saints-redDark saints-focus disabled:cursor-wait disabled:bg-red-300"
        >
          <RefreshCw
            aria-hidden="true"
            className={["h-4 w-4", retrying ? "animate-spin" : ""].join(" ")}
          />
          {retrying ? "Trying again" : "Try again"}
        </button>
      </div>
    </Card>
  );
}

function CurrentPlayerCard({
  highestWeeklyScore,
  player,
}: {
  highestWeeklyScore: number;
  player: LeaderboardPlayer;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="relative bg-saints-black px-4 py-3 text-white">
        <div className="absolute inset-y-0 left-0 w-1 bg-saints-red" aria-hidden="true" />
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-[0.68rem] font-black uppercase tracking-normal text-white/65">
              <Medal aria-hidden="true" className="h-3.5 w-3.5 text-saints-red" />
              Original game scores · rolling 7 days
            </p>
            <h1 className="mt-1 truncate text-xl font-black leading-tight">{player.username}</h1>
          </div>
          <div className="shrink-0 rounded-lg bg-white/10 px-3 py-2 text-right">
            <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
              Rank
            </p>
            <p className="text-xl font-black leading-none">{rankLabel(player)}</p>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
          <div className="min-w-0">
            <p className="text-4xl font-black leading-none">{player.weeklyPoints}</p>
            <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-white/60">
              points in the last 7 days
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-1.5 text-center">
            <div className="min-w-[3.6rem] rounded-lg bg-saints-red px-2 py-1.5">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/70">
                Wordle level
              </p>
              <p className="mt-0.5 text-2xl font-black leading-none">{player.wordleLevel}</p>
            </div>
            <div className="min-w-[3.6rem] rounded-lg bg-white/10 px-2 py-1.5">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
                Best level
              </p>
              <p className="mt-0.5 text-2xl font-black leading-none">{player.bestWordleLevel}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-3 p-3">
        <div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
            <div
              className="h-full rounded-full bg-saints-red"
              style={{ width: percent(player.weeklyPoints, highestWeeklyScore) }}
            />
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
            <span>Rolling 7-day pace</span>
            <span className="whitespace-nowrap">{player.totalPoints} all-time pts</span>
          </div>
        </div>
        <ContributionBar
          mapPoints={player.weeklyMapPoints}
          quizPoints={player.weeklyQuizPoints}
          wordlePoints={player.weeklyWordlePoints}
        />
        <div className="grid grid-cols-4 gap-2">
          <CompactScoreMetric
            icon={Hash}
            label="Wordle"
            value={player.weeklyWordlePoints}
            tone="dark"
          />
          <CompactScoreMetric
            icon={CircleHelp}
            label="Quiz"
            value={player.weeklyQuizPoints}
            tone="red"
          />
          <CompactScoreMetric
            icon={MapPinned}
            label="Map"
            value={player.weeklyMapPoints}
          />
          <CompactScoreMetric
            icon={TrendingUp}
            label="7-day total"
            value={player.weeklyPoints}
          />
        </div>
      </div>
    </Card>
  );
}

function ScoreRow({
  isCurrentUser,
  onSelect,
  player,
}: {
  isCurrentUser: boolean;
  onSelect: () => void;
  player: LeaderboardPlayer;
}) {
  return (
    <tr
      tabIndex={0}
      role="button"
      aria-label={`Open stats for ${player.username}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className="cursor-pointer border-t border-slate-100 transition hover:bg-saints-redSoft focus:bg-saints-redSoft focus:outline-none"
    >
      <td className="min-w-0 px-3 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-saints-black text-sm font-black text-white">
            {player.weeklyPoints > 0 ? player.rank : "—"}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-black text-slate-950">{player.username}</p>
            {isCurrentUser ? (
              <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                You
              </p>
            ) : null}
          </div>
        </div>
      </td>
      <td className="px-2 py-3 text-right text-base font-black text-slate-950">
        {player.weeklyPoints}
      </td>
      <td className="px-3 py-3 text-right">
        <span className="inline-flex min-w-9 items-center justify-center rounded-full bg-slate-100 px-2.5 py-1 text-sm font-black leading-none text-slate-950">
          {player.wordleLevel}
        </span>
      </td>
    </tr>
  );
}

function ContributionBar({
  mapPoints,
  quizPoints,
  wordlePoints,
}: {
  mapPoints: number;
  quizPoints: number;
  wordlePoints: number;
}) {
  const scoredPoints = quizPoints + wordlePoints + mapPoints;
  const segments = [
    { className: "bg-saints-black", label: "Wordle", points: wordlePoints },
    { className: "bg-saints-red", label: "Quiz", points: quizPoints },
    { className: "bg-emerald-500", label: "Map", points: mapPoints },
  ];
  return (
    <div>
      <div
        className="flex h-3 overflow-hidden rounded-full bg-slate-100"
        aria-label={`Rolling 7-day contribution: Wordle ${wordlePoints}, Quiz ${quizPoints}, Map ${mapPoints}`}
      >
        {scoredPoints > 0
          ? segments.map((segment) => (
              <span
                key={segment.label}
                className={["h-full min-w-0", segment.className].join(" ")}
                style={{ flexBasis: 0, flexGrow: segment.points }}
                title={`${segment.label}: ${segment.points} points`}
              />
            ))
          : null}
      </div>
      <div className="mt-1 grid grid-cols-3 gap-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
        <span>Wordle {wordlePoints}</span>
        <span className="text-center">Quiz {quizPoints}</span>
        <span className="text-right">Map {mapPoints}</span>
      </div>
    </div>
  );
}

function CompactScoreMetric({
  icon: Icon,
  label,
  tone = "neutral",
  value,
}: {
  icon: LucideIcon;
  label: string;
  tone?: "dark" | "neutral" | "red";
  value: number | string;
}) {
  const toneClasses = {
    dark: "bg-saints-black text-white",
    neutral: "bg-slate-50 text-slate-950",
    red: "bg-saints-redSoft text-slate-950",
  };
  const iconClasses = {
    dark: "text-saints-red",
    neutral: "text-slate-500",
    red: "text-saints-red",
  };

  return (
    <div
      className={[
        "flex min-h-[4.15rem] flex-col justify-center rounded-lg border border-slate-200 px-2 py-2 text-center shadow-sm",
        toneClasses[tone],
      ].join(" ")}
    >
      <Icon
        aria-hidden="true"
        className={["mx-auto h-4 w-4", iconClasses[tone]].join(" ")}
        strokeWidth={2.6}
      />
      <p className="mt-1 text-xl font-black leading-none">{value}</p>
      <p
        className={[
          "mt-1 text-[0.62rem] font-black uppercase leading-tight tracking-normal",
          tone === "dark" ? "text-white/70" : "text-slate-500",
        ].join(" ")}
      >
        {label}
      </p>
    </div>
  );
}

function PlayerDetailDialog({
  onClose,
  player,
}: {
  onClose: () => void;
  player: LeaderboardPlayer | null;
}) {
  if (player === null) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/55 p-3 backdrop-blur-sm min-[540px]:items-center"
      onMouseDown={onClose}
    >
      <Card
        as="div"
        role="dialog"
        aria-modal="true"
        aria-labelledby="player-stats-title"
        onMouseDown={(event) => event.stopPropagation()}
        className="max-h-[85dvh] w-full max-w-[460px] overflow-y-auto p-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-normal text-saints-red">
              Player stats
            </p>
            <h2
              id="player-stats-title"
              className="mt-1 break-words text-2xl font-black leading-tight text-slate-950"
            >
              {player.username}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close player stats"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-950 transition hover:bg-saints-red hover:text-white focus:outline-none focus:ring-4 focus:ring-saints-red/20"
          >
            <X aria-hidden="true" className="h-5 w-5" strokeWidth={2.5} />
          </button>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3">
          <StatFigure label="7-day rank" value={rankLabel(player)} />
          <StatFigure label="Last 7 days" value={player.weeklyPoints} />
          <StatFigure label="Level" value={player.wordleLevel} />
        </div>

        <div className="mt-4 space-y-3">
          <ContributionBar
            mapPoints={player.weeklyMapPoints}
            quizPoints={player.weeklyQuizPoints}
            wordlePoints={player.weeklyWordlePoints}
          />
          <div className="space-y-2">
            <DetailMetricRow
              icon={Hash}
              label="Wordle score"
              value={`${player.wordlePoints} pts`}
              detail={`${player.wordleWins} wins from ${player.wordlePlayed} games, including +${player.wordleDifficultyBonus} level bonus`}
            />
            <DetailMetricRow
              icon={Gauge}
              label="Wordle level"
              value={`${player.wordleLevel}`}
              detail={`Best level earned: ${player.bestWordleLevel}`}
            />
            <DetailMetricRow
              icon={CircleHelp}
              label="Quiz points"
              value={`${player.quizPoints} pts`}
              detail={`${quizAccuracy(player)} accuracy from ${player.quizCorrect} correct answers`}
            />
            <DetailMetricRow
              icon={MapPinned}
              label="Map points"
              value={`${player.mapPoints} pts`}
              detail={`${player.mapPlayed} locked map guesses`}
            />
            <DetailMetricRow
              icon={Hash}
              label="All-time total"
              value={`${player.totalPoints} pts`}
              detail="Permanent score across all games"
            />
            <DetailMetricRow
              icon={TrendingUp}
              label="7-day level bonus"
              value={`+${player.weeklyWordleDifficultyBonus} pts`}
              detail="Included in the rolling 7-day Wordle total"
            />
          </div>
        </div>
      </Card>
    </div>,
    document.body,
  );
}

function ScoreGuide() {
  return (
    <Card className="p-4 sm:p-5">
      <div className="space-y-4">
        <div className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-3 gap-y-2 min-[720px]:grid-cols-[3rem_minmax(0,1fr)_auto]">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-saints-red text-white shadow-sm">
            <Info aria-hidden="true" className="h-6 w-6" strokeWidth={2.8} />
          </span>
          <div className="min-w-0 pt-0.5">
            <h2 className="text-[1.25rem] font-black leading-tight text-slate-950 min-[390px]:text-[1.35rem]">
              How points work
            </h2>
            <p className="mt-1 text-[0.82rem] font-semibold leading-snug text-slate-500 min-[390px]:text-sm">
              Your guide to earning points in Quiz, Wordle and Map.
            </p>
          </div>
          <div className="col-start-2 flex min-w-0 items-center self-center justify-self-start rounded-full border border-saints-red/35 bg-white px-3 py-2 text-saints-red min-[720px]:col-start-3 min-[720px]:row-start-1 min-[720px]:justify-self-end">
            <CalendarDays aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={2.4} />
            <span className="ml-2 whitespace-nowrap text-[0.66rem] font-black leading-none text-slate-950 min-[390px]:text-[0.7rem]">
              Daily scoring guide
            </span>
          </div>
        </div>

        <div className="h-px bg-slate-200" aria-hidden="true" />

        <section className="space-y-4">
          <GuideSectionTitle icon={CircleHelp} title="Quiz" />
          <div className="grid grid-cols-[minmax(0,1fr)_1rem_minmax(0,1fr)_1rem_minmax(0,1fr)_1rem_minmax(0,1fr)] items-stretch gap-x-0.5">
            {QUIZ_JOURNEY.map((step, index) => (
              <QuizJourneyCard
                key={step.label}
                icon={step.icon}
                isLast={index === QUIZ_JOURNEY.length - 1}
                label={step.label === "Perfect round" ? "Perfect" : step.label}
                value={step.value}
                variant={step.label === "Perfect round" ? "perfect" : "standard"}
              />
            ))}
          </div>
        </section>

        <div className="h-px bg-slate-200" aria-hidden="true" />

        <section className="space-y-4">
          <GuideSectionTitle icon={MapPinned} title="Map" />
          <p className="pl-10 text-[0.76rem] font-bold leading-snug text-slate-600 min-[390px]:text-sm">
            One place each day. Lock the correct place; each reveal reduces the maximum score.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <JourneyInfoCard
              body="10 pts"
              cardClassName="border-slate-200 bg-gradient-to-br from-white via-white to-slate-50"
              icon={Trophy}
              iconClassName="bg-slate-100 text-slate-950 ring-1 ring-slate-200"
              title="Hard clue"
            />
            <JourneyInfoCard
              body="7 pts"
              cardClassName="border-red-200 bg-gradient-to-br from-white via-white to-red-50/70"
              icon={CircleHelp}
              iconClassName="bg-red-50 text-saints-red ring-1 ring-red-100"
              title="Medium clue"
            />
            <JourneyInfoCard
              body="5 pts"
              cardClassName="border-emerald-200 bg-gradient-to-br from-white via-white to-emerald-50/70"
              icon={MapPinned}
              iconClassName="bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100"
              title="Easy clue"
            />
            <JourneyInfoCard
              body="2 pts"
              cardClassName="border-amber-200 bg-gradient-to-br from-white via-white to-amber-50/70"
              icon={Info}
              iconClassName="bg-amber-50 text-amber-700 ring-1 ring-amber-100"
              title="Place name"
            />
          </div>
        </section>

        <div className="h-px bg-slate-200" aria-hidden="true" />

        <section className="space-y-4">
          <div className="space-y-1">
            <GuideSectionTitle glyph="W" title="Wordle" />
            <p className="pl-10 text-[0.76rem] font-bold leading-tight text-slate-600">
              Guesses ladder <span className="text-slate-400">(fewer is better)</span>
            </p>
          </div>
          <div className="mx-auto max-w-[19.8rem] space-y-0">
            <WordleJourneyRow direction="right" steps={WORDLE_JOURNEY.slice(0, 3)} />
            <WordleTurnConnector />
            <WordleJourneyRow direction="left" steps={[...WORDLE_JOURNEY.slice(3)].reverse()} />
          </div>
          <div className="h-px bg-slate-200" aria-hidden="true" />
          <div className="grid grid-cols-2 gap-2">
            <JourneyInfoCard
              body={"+2 per level"}
              cardClassName="border-slate-200 bg-gradient-to-br from-white via-white to-slate-50"
              icon={Gift}
              iconClassName="bg-slate-100 text-slate-950 ring-1 ring-slate-200"
              title="Bonus"
            />
            <JourneyInfoCard
              body={"Win: up\nMiss: reset"}
              bodyClassName="text-[0.72rem] font-bold leading-snug text-slate-950 min-[390px]:text-[0.76rem]"
              cardClassName="border-red-200 bg-gradient-to-br from-white via-white to-red-50/70"
              icon={TrendingUp}
              iconClassName="bg-red-50 text-saints-red ring-1 ring-red-100"
              title="Level"
            />
          </div>
        </section>
      </div>
    </Card>
  );
}

function GuideSectionTitle({
  glyph,
  icon: Icon,
  title,
}: {
  glyph?: string;
  icon?: LucideIcon;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-950 text-white shadow-sm">
        {Icon ? (
          <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={2.5} />
        ) : (
          <span className="text-[1rem] font-black leading-none">{glyph}</span>
        )}
      </span>
      <h3 className="text-[1.02rem] font-black uppercase tracking-normal text-slate-950">
        {title}
      </h3>
    </div>
  );
}

function QuizJourneyCard({
  icon: Icon,
  isLast,
  label,
  value,
  variant,
}: {
  icon: LucideIcon;
  isLast: boolean;
  label: string;
  value: string;
  variant: "standard" | "perfect";
}) {
  const isPerfect = variant === "perfect";

  return (
    <>
      <div
        className={[
          "grid min-h-[7.25rem] min-w-0 grid-rows-[2.75rem_2.25rem_1.25rem] justify-items-center rounded-xl border px-1 py-3 text-center shadow-sm",
          isPerfect
            ? "border-red-200 bg-red-50/50"
            : "border-slate-200 bg-gradient-to-br from-white via-white to-slate-50",
        ].join(" ")}
      >
        <span
          className={[
            "flex h-11 w-11 items-center justify-center rounded-full border bg-white",
            isPerfect ? "border-saints-red text-saints-red" : "border-slate-700 text-slate-950",
          ].join(" ")}
        >
          <Icon aria-hidden="true" className="h-5 w-5" strokeWidth={isPerfect ? 2.4 : 2.6} />
        </span>
        <p className="mx-auto max-w-[4.5rem] self-center text-[0.7rem] font-bold leading-tight text-slate-950 min-[390px]:text-[0.74rem]">
          {label}
        </p>
        <p
          className={[
            "mx-auto max-w-[4.5rem] self-start whitespace-nowrap text-[0.78rem] font-black leading-tight min-[390px]:text-[0.84rem]",
            isPerfect ? "text-saints-red" : "text-slate-950",
          ].join(" ")}
        >
          {value}
        </p>
      </div>
      {!isLast ? (
        <div className="flex min-h-[7.25rem] min-w-4 shrink-0 items-center justify-center text-slate-700">
          <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={3} />
        </div>
      ) : null}
    </>
  );
}

type WordleJourneyDirection = "left" | "right";
type WordleJourneyStepConfig = (typeof WORDLE_JOURNEY)[number];

function WordleJourneyRow({
  direction,
  steps,
}: {
  direction: WordleJourneyDirection;
  steps: readonly WordleJourneyStepConfig[];
}) {
  return (
    <div className="flex min-w-0 items-center">
      {steps.map((step, index) => {
        return (
          <WordleJourneyStep
            key={step.value}
            direction={direction}
            isLast={index === steps.length - 1}
            value={step.value}
          />
        );
      })}
    </div>
  );
}

function WordleTurnConnector() {
  return (
    <div
      className="grid h-4 grid-cols-[2.5rem_minmax(0,1fr)_2.5rem_minmax(0,1fr)_2.5rem]"
      aria-hidden="true"
    >
      <div className="col-start-5 flex items-center justify-center text-slate-500">
        <span className="relative flex h-4 w-4 items-center justify-center">
          <span className="absolute inset-y-0 left-1/2 -translate-x-1/2 border-l border-dashed border-slate-500" />
          <ArrowDown className="absolute -bottom-1 h-3.5 w-3.5 bg-white" strokeWidth={2.2} />
        </span>
      </div>
    </div>
  );
}

function WordleJourneyStep({
  direction,
  isLast,
  value,
}: {
  direction: WordleJourneyDirection;
  isLast: boolean;
  value: number;
}) {
  return (
    <>
      <div className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-full border border-slate-600 bg-white text-center shadow-sm">
        <span className="text-[1rem] font-black leading-none text-slate-950">{value}</span>
        <span className="mt-0.5 text-[0.58rem] font-black uppercase leading-none tracking-normal text-slate-600">
          {value === 1 ? "pt" : "pts"}
        </span>
      </div>
      {!isLast ? (
        <WordleJourneyConnector direction={direction} />
      ) : null}
    </>
  );
}

function WordleJourneyConnector({
  direction,
}: {
  direction: WordleJourneyDirection;
}) {
  return (
    <div className="relative h-11 min-w-0 flex-1 text-slate-500" aria-hidden="true">
      <span className="absolute left-0 right-0 top-1/2 -translate-y-1/2 border-t border-dashed border-slate-500" />
      <ArrowRight
        className={[
          "absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2",
          direction === "left" ? "left-0 rotate-180" : "right-0",
        ].join(" ")}
        strokeWidth={2.8}
      />
    </div>
  );
}

function JourneyInfoCard({
  body,
  bodyClassName = "text-[0.72rem] font-black leading-snug text-slate-950 min-[390px]:text-[0.76rem]",
  cardClassName,
  icon: Icon,
  iconClassName,
  title,
}: {
  body: string;
  bodyClassName?: string;
  cardClassName: string;
  icon: LucideIcon;
  iconClassName: string;
  title: string;
}) {
  return (
    <div
      className={[
        "flex min-h-[6.75rem] min-w-0 flex-col items-center justify-center rounded-xl border px-2.5 py-3 text-center shadow-sm",
        cardClassName,
      ].join(" ")}
    >
      <span className={["flex h-10 w-10 items-center justify-center rounded-full", iconClassName].join(" ")}>
        <Icon aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
      </span>
      <div className="mt-2 min-w-0">
        <p className="break-words text-[0.82rem] font-black leading-tight text-slate-950 min-[390px]:text-[0.88rem]">{title}</p>
        <span className="mx-auto mt-1.5 block h-1 w-7 rounded-full bg-saints-red" aria-hidden="true" />
        <p className={["mt-1.5 whitespace-pre-line break-words", bodyClassName].join(" ")}>{body}</p>
      </div>
    </div>
  );
}

function StatFigure({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-slate-50 px-3 py-3 text-center">
      <p className="break-words text-2xl font-black leading-none text-slate-950">{value}</p>
      <p className="mt-1 text-[0.72rem] font-black uppercase tracking-normal text-slate-600">
        {label}
      </p>
    </div>
  );
}

function DetailMetricRow({
  detail,
  icon: Icon,
  label,
  value,
}: {
  detail: string;
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-2xl bg-slate-50 px-3 py-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-saints-red">
        <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={2.6} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-col gap-1 min-[360px]:flex-row min-[360px]:items-baseline min-[360px]:justify-between">
          <p className="text-sm font-black uppercase tracking-normal text-slate-600">{label}</p>
          <p className="break-words text-xl font-black leading-tight text-slate-950">{value}</p>
        </div>
        <p className="mt-1 break-words text-sm font-semibold leading-snug text-slate-600">{detail}</p>
      </div>
    </div>
  );
}
