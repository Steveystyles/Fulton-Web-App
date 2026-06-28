import {
  CalendarDays,
  CircleHelp,
  Gauge,
  Hash,
  Info,
  LoaderCircle,
  Medal,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
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

export function Leaderboard() {
  const { user } = useAuth();
  const [board, setBoard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedPlayer, setSelectedPlayer] = useState<LeaderboardPlayer | null>(null);

  useEffect(() => {
    let active = true;

    async function loadScores() {
      try {
        const response = await api.leaderboard();
        if (active) {
          setBoard(response);
          setError("");
        }
      } catch (caughtError) {
        if (active) {
          setError(caughtError instanceof Error ? caughtError.message : "Scores failed to load.");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadScores();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selectedPlayer === null) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedPlayer(null);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedPlayer]);

  const players = board?.players ?? [];
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
      {loading ? (
        <Card>
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm font-black text-slate-500">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading scores
          </div>
        </Card>
      ) : error ? (
        <Card>
          <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
            {error}
          </p>
        </Card>
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
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-black text-slate-950">7-day leaderboard</p>
                {board ? (
                  <p className="mt-0.5 flex items-center gap-1 text-xs font-bold text-slate-500">
                    <CalendarDays aria-hidden="true" className="h-3.5 w-3.5" />
                    {shortDate(board.summary.periodStart)} - {shortDate(board.summary.periodEnd)}
                  </p>
                ) : null}
              </div>
              {board ? (
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                  {board.summary.playerCount} players
                </span>
              ) : null}
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200">
              <table className="w-full border-collapse bg-white text-left" aria-label="Player score table">
                <thead className="bg-slate-50 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Player</th>
                    <th className="px-2 py-2 text-right">This week</th>
                    <th className="px-3 py-2 text-right">Level</th>
                  </tr>
                </thead>
                <tbody>
                  {players.map((player) => (
                    <ScoreRow
                      key={player.id}
                      player={player}
                      isCurrentUser={player.id === user?.id}
                      onSelect={() => setSelectedPlayer(player)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <ScoreGuide />
        </>
      )}

      <PlayerDetailDialog player={selectedPlayer} onClose={() => setSelectedPlayer(null)} />
    </section>
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
              7-day score
            </p>
            <h1 className="mt-1 truncate text-xl font-black leading-tight">{player.username}</h1>
          </div>
          <div className="shrink-0 rounded-lg bg-white/10 px-3 py-2 text-right">
            <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
              Rank
            </p>
            <p className="text-xl font-black leading-none">#{player.rank}</p>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
          <div className="min-w-0">
            <p className="text-4xl font-black leading-none">{player.weeklyPoints}</p>
            <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-white/60">
              points this week
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-1.5 text-center">
            <div className="min-w-[3.6rem] rounded-lg bg-saints-red px-2 py-1.5">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/70">
                Level
              </p>
              <p className="mt-0.5 text-2xl font-black leading-none">{player.wordleLevel}</p>
            </div>
            <div className="min-w-[3.6rem] rounded-lg bg-white/10 px-2 py-1.5">
              <p className="text-[0.62rem] font-black uppercase tracking-normal text-white/60">
                Best
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
            <span>Weekly pace</span>
            <span className="whitespace-nowrap">{player.totalPoints} all-time pts</span>
          </div>
        </div>
        <ContributionBar
          quizPoints={player.weeklyQuizPoints}
          wordlePoints={player.weeklyWordlePoints}
        />
        <div className="grid grid-cols-3 gap-2">
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
            icon={TrendingUp}
            label="Total"
            value={player.totalPoints}
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
            {player.rank}
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

function ContributionBar({ quizPoints, wordlePoints }: { quizPoints: number; wordlePoints: number }) {
  const scoredPoints = Math.max(1, quizPoints + wordlePoints);
  return (
    <div>
      <div className="h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
        <div
          className="h-full bg-saints-black"
          style={{ width: percent(wordlePoints, scoredPoints), float: "left" }}
        />
        <div
          className="h-full bg-saints-red"
          style={{ width: percent(quizPoints, scoredPoints), float: "left" }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
        <span>Wordle {wordlePoints}</span>
        <span>Quiz {quizPoints}</span>
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
          <StatFigure label="Rank" value={`#${player.rank}`} />
          <StatFigure label="This week" value={player.weeklyPoints} />
          <StatFigure label="Level" value={player.wordleLevel} />
        </div>

        <div className="mt-4 space-y-3">
          <ContributionBar
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
              icon={Hash}
              label="All-time total"
              value={`${player.totalPoints} pts`}
              detail="Permanent score across all games"
            />
            <DetailMetricRow
              icon={TrendingUp}
              label="This week's level bonus"
              value={`+${player.weeklyWordleDifficultyBonus} pts`}
              detail="Included in the Wordle total above"
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
    <Card className="overflow-hidden p-0">
      <div className="flex items-center gap-2 bg-slate-950 px-4 py-3 text-white">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-saints-red">
          <Info aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-black">How scoring works</h2>
          <p className="text-xs font-bold leading-snug text-white/60">
            Quiz and Wordle both count.
          </p>
        </div>
      </div>
      <div className="space-y-3 p-3">
        <ScoreRuleGroup icon={CircleHelp} title="Quiz">
          <div className="grid grid-cols-3 gap-2">
            <ScoreRuleCell label="Easy" value="1 pt" />
            <ScoreRuleCell label="Medium" value="3 pts" />
            <ScoreRuleCell label="Hard" value="5 pts" />
          </div>
          <div className="mt-2 rounded-lg border border-red-100 bg-saints-redSoft px-3 py-2 text-center">
            <p className="text-[0.62rem] font-black uppercase tracking-normal text-saints-red">
              Perfect round
            </p>
            <p className="mt-1 text-sm font-black leading-tight text-slate-950">+3 bonus pts</p>
          </div>
        </ScoreRuleGroup>
        <ScoreRuleGroup icon={Hash} title="Wordle">
          <div className="grid grid-cols-3 gap-2">
            <ScoreRuleCell label="Guesses" value="10/5/4/3/2/1" />
            <ScoreRuleCell label="Bonus" value={"+2 per\nlevel"} tone="red" />
            <ScoreRuleCell label="Next level" value={"Win +1\nMiss -> 1"} />
          </div>
        </ScoreRuleGroup>
      </div>
    </Card>
  );
}

function ScoreRuleGroup({
  children,
  icon: Icon,
  title,
}: {
  children: ReactNode;
  icon: LucideIcon;
  title: string;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-700">
          <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
        </span>
        <h3 className="text-xs font-black uppercase tracking-normal text-slate-700">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function ScoreRuleCell({
  label,
  tone = "neutral",
  value,
}: {
  label: string;
  tone?: "neutral" | "red";
  value: string;
}) {
  return (
    <div
      className={[
        "flex min-h-[3.75rem] flex-col justify-center rounded-lg border border-slate-200 px-1.5 py-2 text-center shadow-sm",
        tone === "red" ? "bg-saints-redSoft" : "bg-slate-50",
      ].join(" ")}
    >
      <p
        className={[
          "text-[0.62rem] font-black uppercase leading-tight tracking-normal",
          tone === "red" ? "text-saints-red" : "text-slate-500",
        ].join(" ")}
      >
        {label}
      </p>
      <p className="mt-1 whitespace-pre-line text-[0.78rem] font-black leading-tight text-slate-950">
        {value}
      </p>
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
