import { Flame, Hash, LoaderCircle, Medal, Trophy, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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

function dayLabel(value: number) {
  return `${value} day${value === 1 ? "" : "s"}`;
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
  const highestScore = useMemo(
    () => players.reduce((highest, player) => Math.max(highest, player.totalPoints), 0),
    [players],
  );

  return (
    <section className="page-fade space-y-3" aria-label="Scores">
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
            <CurrentPlayerCard player={currentPlayer} highestScore={highestScore} />
          ) : null}

          <Card className="p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs font-bold text-slate-500">
                Select a player for the full breakdown.
              </p>
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
                    <th className="px-2 py-2 text-right">Score</th>
                    <th className="px-3 py-2 text-right">Streak</th>
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
        </>
      )}

      <PlayerDetailDialog player={selectedPlayer} onClose={() => setSelectedPlayer(null)} />
    </section>
  );
}

function CurrentPlayerCard({
  highestScore,
  player,
}: {
  highestScore: number;
  player: LeaderboardPlayer;
}) {
  const scoredPoints = Math.max(1, player.totalPoints);

  return (
    <Card className="overflow-hidden p-0">
      <div className="bg-saints-black px-4 py-4 text-white">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-[0.68rem] font-black uppercase tracking-normal text-white/65">
              <Medal aria-hidden="true" className="h-3.5 w-3.5 text-saints-red" />
              Your stats
            </p>
            <h1 className="mt-1 truncate text-2xl font-black">{player.username}</h1>
          </div>
          <div className="shrink-0 rounded-2xl bg-white/10 px-3 py-2 text-right">
            <p className="text-[0.68rem] font-black uppercase tracking-normal text-white/60">
              Rank
            </p>
            <p className="text-2xl font-black leading-none">#{player.rank}</p>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
          <div>
            <p className="text-5xl font-black leading-none">{player.totalPoints}</p>
            <p className="mt-1 text-xs font-black uppercase tracking-normal text-white/60">
              total points
            </p>
          </div>
          <div className="text-right">
            <p className="inline-flex items-center gap-1 rounded-full bg-saints-red px-2.5 py-1 text-xs font-black">
              <Flame aria-hidden="true" className="h-3.5 w-3.5" />
              {dayLabel(player.currentStreak)}
            </p>
            <p className="mt-1 text-xs font-black uppercase tracking-normal text-white/60">
              best {player.bestStreak}
            </p>
          </div>
        </div>

        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
          <div
            className="h-full rounded-full bg-saints-red"
            style={{ width: percent(player.totalPoints, highestScore) }}
          />
        </div>
      </div>

      <div className="space-y-3 p-3">
        <ContributionBar player={player} scoredPoints={scoredPoints} />
        <div className="grid grid-cols-2 gap-2">
          <ScoreFigure
            icon={Hash}
            label="Wordle"
            value={`${player.wordlePoints} pts`}
            detail={`${player.wordleWins}/${player.wordlePlayed} wins`}
          />
          <ScoreFigure
            icon={Trophy}
            label="Quiz"
            value={`${player.quizPoints} pts`}
            detail={`${player.quizCorrect} correct`}
          />
          <StatFigure label="Quiz plays" value={player.quizPlayed} />
          <StatFigure label="Best streak" value={player.bestStreak} />
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
        {player.totalPoints}
      </td>
      <td className="px-3 py-3 text-right">
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-black text-slate-700">
          <Flame aria-hidden="true" className="h-3.5 w-3.5 text-saints-red" />
          {player.currentStreak}
        </span>
      </td>
    </tr>
  );
}

function ContributionBar({
  player,
  scoredPoints,
}: {
  player: LeaderboardPlayer;
  scoredPoints: number;
}) {
  return (
    <div>
      <div className="h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
        <div
          className="h-full bg-saints-black"
          style={{ width: percent(player.wordlePoints, scoredPoints), float: "left" }}
        />
        <div
          className="h-full bg-emerald-500"
          style={{ width: percent(player.quizPoints, scoredPoints), float: "left" }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
        <span>Wordle</span>
        <span>Quiz</span>
      </div>
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
        className="max-h-[85dvh] w-full max-w-[430px] overflow-y-auto p-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-normal text-saints-red">
              Player stats
            </p>
            <h2 id="player-stats-title" className="mt-1 truncate text-2xl font-black text-slate-950">
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

        <div className="mt-4 grid grid-cols-3 gap-2">
          <StatFigure label="Rank" value={`#${player.rank}`} />
          <StatFigure label="Score" value={player.totalPoints} />
          <StatFigure label="Streak" value={player.currentStreak} />
        </div>

        <div className="mt-4 space-y-3">
          <ContributionBar player={player} scoredPoints={Math.max(1, player.totalPoints)} />
          <div className="grid grid-cols-2 gap-2">
            <ScoreFigure
              icon={Hash}
              label="Wordle points"
              value={player.wordlePoints}
              detail={`${player.wordleWins} wins from ${player.wordlePlayed}`}
            />
            <ScoreFigure
              icon={Trophy}
              label="Quiz points"
              value={player.quizPoints}
              detail={`${player.quizCorrect} correct`}
            />
            <StatFigure label="Quiz max" value={player.quizMaxPoints} />
            <StatFigure label="Best streak" value={player.bestStreak} />
            <StatFigure label="Quiz plays" value={player.quizPlayed} />
            <StatFigure label="Wordles" value={player.wordlePlayed} />
          </div>
        </div>
      </Card>
    </div>,
    document.body,
  );
}

function StatFigure({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-slate-50 px-2.5 py-3 text-center">
      <p className="truncate text-lg font-black leading-none text-slate-950">{value}</p>
      <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
    </div>
  );
}

function ScoreFigure({
  detail,
  icon: Icon,
  label,
  value,
}: {
  detail: string;
  icon: typeof Hash;
  label: string;
  value: number | string;
}) {
  return (
    <div className="flex min-w-0 items-start gap-2 rounded-2xl bg-slate-50 p-2.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-saints-red">
        <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2.6} />
      </span>
      <div className="min-w-0">
        <p className="text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
          {label}
        </p>
        <p className="truncate text-sm font-black text-slate-950">{value}</p>
        <p className="truncate text-xs font-bold text-slate-500">{detail}</p>
      </div>
    </div>
  );
}
