type StatCardProps = {
  label: string;
  value: string;
  detail: string;
};

export function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-bold uppercase tracking-normal text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-2xl font-black leading-none text-slate-950">
        {value}
      </p>
      <p className="mt-1 text-sm font-semibold text-slate-600">{detail}</p>
    </div>
  );
}
