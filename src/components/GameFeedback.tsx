import { useState } from "react";
import { api } from "../lib/api";

const options = [["fun", "Fun"], ["fair", "Fair"], ["too_hard", "Too hard"], ["unclear", "Unclear"]] as const;

export function GameFeedback({ game }: { game: "quiz" | "map" }) {
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  async function choose(rating: typeof options[number][0]) {
    setSelected(rating); setMessage("");
    try { await api.feedback(game, rating); setMessage("Thanks — feedback saved."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Feedback could not be saved."); }
  }
  return <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
    <p className="text-sm font-black">How did that feel? <span className="font-normal text-slate-500">Optional</span></p>
    <div className="mt-2 grid grid-cols-2 gap-2">{options.map(([value, label]) => <button key={value} type="button" aria-pressed={selected === value} onClick={() => void choose(value)} className={`min-h-11 rounded-lg border px-2 text-sm font-bold saints-focus ${selected === value ? "border-saints-black bg-saints-black text-white" : "bg-white"}`}>{label}</button>)}</div>
    {message ? <p role="status" className="mt-2 text-xs text-slate-600">{message}</p> : null}
  </div>;
}
