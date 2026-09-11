import { CircleHelp, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { DialogPortal } from "./DialogPortal";

/** Instructions stay out of the game layout until explicitly requested. */
export function HelpButton({ title, children, compact = false }: { title: string; children: ReactNode; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <>
    <button type="button" aria-label={title} title={title} aria-haspopup="dialog" aria-expanded={open} aria-controls={id}
      onClick={() => setOpen(true)} className={`saints-focus inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white text-sm font-bold text-slate-800 ${compact ? "w-11" : "max-w-full px-3 py-2 text-left"}`}>
      <CircleHelp aria-hidden="true" className="h-5 w-5 shrink-0" />{compact ? null : <span>{title}</span>}
    </button>
    {open ? <DialogPortal onClose={() => setOpen(false)}>
      <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/60 p-3">
        <section id={id} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-4 shadow-xl">
          <div className="flex items-center justify-between gap-3"><h2 id={`${id}-title`} className="min-w-0 text-xl font-black">{title}</h2><button type="button" aria-label={`Close ${title}`} onClick={() => setOpen(false)} className="saints-focus flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border"><X aria-hidden="true" className="h-5 w-5" /></button></div>
          <div className="mt-3 text-sm leading-relaxed">{children}</div>
          <button type="button" onClick={() => setOpen(false)} className="saints-focus mt-4 min-h-11 w-full rounded-lg bg-saints-black px-3 py-2 font-bold text-white">Done</button>
        </section>
      </div>
    </DialogPortal> : null}
  </>;
}
