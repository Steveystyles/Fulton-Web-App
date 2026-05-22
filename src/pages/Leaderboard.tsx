import { BarChart3, Flame, Hash, LoaderCircle, Medal, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { api, type LeaderboardResponse } from "../lib/api";

function percent(value: number, maximum: number) {
  if (maximum <= 0 || value <= 0) {
    return "0%";
  }
  return `${Math.max(4, Math.round((value / maximum) * 100))}%`;
}

export function Leaderboard() {
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

  return (
    <section className="page-fade space-y-3" aria-label="Scores">
      <Card>
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-saints-red text-white">
            <Medal aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-black text-slate-950">Scores</p>
            <p className="mt-1 text-sm font-semibold text-slate-600">
              Quiz and Wordle points for player accounts.
            </p>
          </div>
        </div>

        {board ? (
          <div className="mt-4 grid grid-cols-2 gap-2" aria-label="Score summary">
            <ScoreStat label="Players" value={board.summary.playerCount} />
            <ScoreStat label="Quiz plays" value={board.summary.quizPlays} />
            <ScoreStat label="Wordles" value={board.summary.wordlePlays} />
            <ScoreStat label="Best streak" value={board.summary.bestStreak} />
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
        <Card className="p-2">
          <div className="space-y-2" aria-label="Player leaderboard">
            {players.map((player) => {
              const scoredPoints = Math.max(1, player.totalPoints);
              return (
                <article
                  key={player.id}
                  className="rounded-2xl border border-slate-200 bg-white p-3"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-black text-base font-black text-white">
                      {player.rank}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-base font-black text-slate-950">
                        {player.username}
                      </p>
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
          </div>
        </Card>
      )}
    </section>
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
