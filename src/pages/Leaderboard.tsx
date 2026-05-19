import { Medal } from "lucide-react";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";

const rows = [
  { rank: "1", name: "Dad", points: "120 pts" },
  { rank: "2", name: "Friend 1", points: "98 pts" },
  { rank: "3", name: "Friend 2", points: "87 pts" },
];

export function Leaderboard() {
  return (
    <PageContainer title="LEADERBOARD" number="4">
      <Card>
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-saints-red text-white">
            <Medal aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
          </div>
          <div>
            <p className="text-xl font-black text-slate-950">Friend rankings</p>
            <p className="mt-1 text-sm font-semibold text-slate-600">
              Placeholder table for future scoring.
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-2">
        <div className="space-y-2" aria-label="Leaderboard placeholder rows">
          {rows.map((row) => (
            <div
              key={row.rank}
              className="flex min-h-16 items-center gap-3 rounded-2xl bg-slate-50 px-3"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-black text-base font-black text-white">
                {row.rank}
              </span>
              <span className="min-w-0 flex-1 text-base font-black text-slate-950">
                {row.name}
              </span>
              <span className="rounded-full bg-white px-3 py-1.5 text-sm font-black text-saints-red shadow-sm">
                {row.points}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </PageContainer>
  );
}
