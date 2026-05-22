import { BarChart3, Crown, Flame, Hash, LoaderCircle, Medal, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { useAuth } from "../context/AuthContext";
import { api, type LeaderboardResponse } from "../lib/api";

function percent(value: number, maximum: number) {
  if (maximum <= 0 || value <= 0) {
    return "0%";
  }
  return `${Math.max(4, Math.round((value / maximum) * 100))}%`;
}

export function Leaderboard() {
  const { user } = useAuth();
  const [board, setBoard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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

  const players = board?.players ?? [];
  const highestScore = useMemo(
    () => players.reduce((highest, player) => Math.max(highest, player.totalPoints), 0),
    [players],
  );
  const podium = players.slice(0, 3);
  const leader = podium[0];

  return (
    <section className="page-fade space-y-3" aria-label="Scores">
      <Card className="overflow-hidden p-0">
        <div className="bg-saints-black px-4 py-4 text-white">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-saints-red">
              <Medal aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-black">Scores</p>
              <p className="mt-0.5 text-sm font-semibold text-white/70">
                Quiz, Wordle and streak form.
              </p>
            </div>
          </div>

          {leader ? (
            <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl border border-white/15 bg-white/10 p-3">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-[0.68rem] font-black uppercase tracking-normal text-white/60">
                  <Crown aria-hidden="true" className="h-3.5 w-3.5 text-amber-300" />
                  Current leader
                </p>
                <p className="mt-1 truncate text-lg font-black">{leader.username}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-2xl font-black leading-none">{leader.totalPoints}</p>
                <p className="mt-1 text-xs font-black uppercase tracking-normal text-white/60">
                  points
                </p>
              </div>
            </div>
          ) : null}
        </div>

        {board ? (
          <div className="grid grid-cols-2 gap-2 p-3" aria-label="Score summary">
            <ScoreStat label="Players" value={board.summary.playerCount} />
            <ScoreStat label="Best streak" value={board.summary.bestStreak} />
            <ScoreStat label="Quiz plays" value={board.summary.quizPlays} />
            <ScoreStat label="Wordles" value={board.summary.wordlePlays} />
          </div>
        ) : null}
      </Card>

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
          {podium.length > 0 ? (
            <section className="grid grid-cols-1 gap-2 min-[390px]:grid-cols-3" aria-label="Leaderboard leaders">
              {podium.map((player) => (
                <PodiumPlayer key={player.id} player={player} isCurrentUser={player.id === user?.id} />
              ))}
            </section>
          ) : null}

          <section className="space-y-2" aria-label="Player leaderboard">
            {players.map((player) => {
              const scoredPoints = Math.max(1, player.totalPoints);
              return (
                <article
                  key={player.id}
                  className={[
                    "rounded-2xl border bg-white p-3 shadow-soft",
                    player.id === user?.id
                      ? "border-saints-red ring-2 ring-saints-red/10"
                      : "border-slate-200",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-black text-base font-black text-white">
                      {player.rank}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-base font-black text-slate-950">
                        {player.username}
                      </p>
                      {player.id === user?.id ? (
                        <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">
                          Your score
                        </p>
                      ) : null}
                      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-saints-red"
                          style={{ width: percent(player.totalPoints, highestScore) }}
                        />
                      </div>
                    </div>
                    <span className="rounded-full bg-saints-redSoft px-3 py-1.5 text-sm font-black text-saints-red">
                      {player.totalPoints} pts
                    </span>
                  </div>

                  <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                    <div
                      className="h-full bg-saints-black"
                      style={{
                        width: percent(player.wordlePoints, scoredPoints),
                        float: "left",
                      }}
                    />
                    <div
                      className="h-full bg-emerald-500"
                      style={{
                        width: percent(player.quizPoints, scoredPoints),
                        float: "left",
                      }}
                    />
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[0.68rem] font-black uppercase tracking-normal text-slate-400">
                    <span>Wordle</span>
                    <span>Quiz</span>
                  </div>

                  <div className="mt-3 grid grid-cols-1 gap-2 min-[390px]:grid-cols-3">
                    <ScoreDetail
                      icon={Hash}
                      label="Wordle"
                      value={`${player.wordlePoints} pts`}
                      detail={`${player.wordleWins}/${player.wordlePlayed} wins`}
                    />
                    <ScoreDetail
                      icon={Trophy}
                      label="Quiz"
                      value={`${player.quizPoints} pts`}
                      detail={`${player.quizCorrect} correct`}
                    />
                    <ScoreDetail
                      icon={Flame}
                      label="Streak"
                      value={`${player.currentStreak} day${player.currentStreak === 1 ? "" : "s"}`}
                      detail={`Best ${player.bestStreak}`}
                    />
                  </div>
                </article>
              );
            })}
          </section>
        </>
      )}
    </section>
  );
}

function PodiumPlayer({
  isCurrentUser,
  player,
}: {
  isCurrentUser: boolean;
  player: LeaderboardResponse["players"][number];
}) {
  const podiumTone =
    player.rank === 1
      ? "border-amber-300 bg-amber-50"
      : player.rank === 2
        ? "border-slate-300 bg-slate-50"
        : "border-orange-200 bg-orange-50";

  return (
    <article className={`rounded-2xl border p-3 shadow-soft ${podiumTone}`}>
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-saints-black text-sm font-black text-white">
          {player.rank}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-white/85 px-2 py-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-600">
          <Flame aria-hidden="true" className="h-3 w-3 text-saints-red" />
          {player.currentStreak}
        </span>
      </div>
      <p className="mt-3 truncate text-sm font-black text-slate-950">{player.username}</p>
      {isCurrentUser ? (
        <p className="text-[0.68rem] font-black uppercase tracking-normal text-saints-red">You</p>
      ) : null}
      <p className="mt-2 text-2xl font-black leading-none text-saints-black">
        {player.totalPoints}
      </p>
      <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
        points
      </p>
    </article>
  );
}

function ScoreStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl bg-slate-50 px-2 py-3 text-center">
      <p className="text-lg font-black leading-none text-slate-950">{value}</p>
      <p className="mt-1 text-[0.68rem] font-black uppercase tracking-normal text-slate-500">
        {label}
      </p>
    </div>
  );
}

function ScoreDetail({
  detail,
  icon: Icon,
  label,
  value,
}: {
  detail: string;
  icon: typeof BarChart3;
  label: string;
  value: string;
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
