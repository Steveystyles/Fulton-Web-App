const headline = "St Mirren defeat Rangers 2-1 at home...";

export function NewsTicker() {
  return (
    <section
      className="border-y border-white/10 bg-saints-deep text-white"
      aria-label="Breaking news placeholder ticker"
    >
      <div className="flex min-h-10 items-center gap-3 overflow-hidden pl-4">
        <span className="rounded-sm bg-saints-red px-2.5 py-1 text-xs font-black uppercase leading-none text-white">
          Breaking
        </span>
        <div className="ticker-frame min-w-0 flex-1 overflow-hidden" tabIndex={0}>
          <div className="ticker-track flex w-max items-center gap-8 whitespace-nowrap text-sm font-semibold text-white/[0.88]">
            <span>{headline}</span>
            <span aria-hidden="true">{headline}</span>
            <span aria-hidden="true">{headline}</span>
            <span aria-hidden="true">{headline}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
