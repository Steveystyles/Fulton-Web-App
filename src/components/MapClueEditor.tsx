import { useEffect, useState } from "react";
import { Card } from "./Card";
import { api, type AdminMapClueLevel, type AdminMapClues } from "../lib/api";

type ClueField = "hard" | "medium" | "easy" | "reveal";
const FIELDS: ClueField[] = ["hard", "medium", "easy", "reveal"];
const LIMITS: Record<ClueField, number> = { hard: 320, medium: 220, easy: 220, reveal: 240 };
const LABELS: Record<ClueField, string> = {
  hard: "Opening clue",
  medium: "Second clue",
  easy: "Final clue",
  reveal: "Answer reveal",
};

export function MapClueEditor() {
  const [requestedDate, setRequestedDate] = useState("");
  const [puzzle, setPuzzle] = useState<AdminMapClues | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<AdminMapClueLevel["level"] | "">("");
  const [draft, setDraft] = useState<AdminMapClueLevel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function chooseLevel(result: AdminMapClues, level?: AdminMapClueLevel["level"]) {
    const chosen = result.levels.find((item) => item.level === level) ?? result.levels[0] ?? null;
    setPuzzle(result);
    setRequestedDate(result.date);
    setSelectedLevel(chosen?.level ?? "");
    setDraft(chosen ? { ...chosen } : null);
  }

  useEffect(() => {
    let active = true;
    void api.adminMapClues().then((result) => {
      if (active) chooseLevel(result);
    }).catch((caughtError) => {
      if (active) setError(caughtError instanceof Error ? caughtError.message : "Map clues failed to load.");
    });
    return () => { active = false; };
  }, []);

  async function loadDate() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.adminMapClues(requestedDate);
      chooseLevel(result);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Map clues failed to load.");
    } finally {
      setBusy(false);
    }
  }

  function selectLevel(level: AdminMapClueLevel["level"]) {
    const selected = puzzle?.levels.find((item) => item.level === level);
    setSelectedLevel(level);
    setDraft(selected ? { ...selected } : null);
    setError("");
    setMessage("");
  }

  async function save() {
    if (!draft || !puzzle) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.reviseMapClues({
        date: puzzle.date,
        level: draft.level,
        expectedPlaceId: draft.placeId,
        clues: { hard: draft.hard, medium: draft.medium, easy: draft.easy, reveal: draft.reveal },
      });
      chooseLevel(result, draft.level);
      setMessage("Clues saved. Players will see the revised wording when they load this round.");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Map clues were not saved.");
    } finally {
      setBusy(false);
    }
  }

  const original = puzzle?.levels.find((item) => item.level === selectedLevel);
  const changed = draft && original && FIELDS.some((field) => draft[field] !== original[field]);

  return (
    <Card>
      <div className="space-y-4">
        <div>
          <h2 className="text-xl font-black text-slate-950">Map clue editor</h2>
          <p className="mt-1 text-sm text-slate-600">
            Correct a published round without changing its answer or scoring. This admin view shows the answer; keep it private.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex-1 text-sm font-bold text-slate-700">
            Round date
            <input type="date" value={requestedDate} onChange={(event) => setRequestedDate(event.target.value)}
              className="mt-1 h-11 w-full min-w-40 rounded-xl border border-slate-300 bg-white px-3 text-slate-950" />
          </label>
          <button type="button" onClick={() => void loadDate()} disabled={busy || !requestedDate || !!changed}
            className="h-11 rounded-xl bg-slate-950 px-4 text-sm font-black text-white disabled:opacity-50">Load round</button>
        </div>
        {puzzle && puzzle.levels.length === 0 ? (
          <p className="rounded-xl bg-slate-100 p-3 text-sm font-semibold text-slate-700">No published Map round for {puzzle.date}.</p>
        ) : null}
        {draft ? (
          <div className="space-y-3">
            <p className="text-xs font-bold text-slate-500">Editing {puzzle?.date}</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Map level">
              {puzzle?.levels.map((item) => (
                <button key={item.level} type="button" onClick={() => selectLevel(item.level)}
                  disabled={!!changed && selectedLevel !== item.level}
                  aria-pressed={selectedLevel === item.level}
                  className={`rounded-full px-4 py-2 text-sm font-black capitalize disabled:opacity-50 ${selectedLevel === item.level ? "bg-saints-red text-white" : "bg-slate-100 text-slate-700"}`}>
                  {item.level}
                </button>
              ))}
            </div>
            <p className="rounded-xl bg-amber-50 p-3 text-sm font-bold text-amber-900">Answer: {draft.answer}</p>
            {FIELDS.map((field) => (
              <label key={field} className="block text-sm font-black text-slate-800">
                {LABELS[field]} {field === "reveal" ? "(shown after scoring)" : ""}
                <textarea value={draft[field]} maxLength={LIMITS[field]} rows={field === "hard" ? 3 : 2}
                  onChange={(event) => setDraft((current) => current ? { ...current, [field]: event.target.value } : current)}
                  className="mt-1 w-full rounded-xl border border-slate-300 bg-white p-3 text-base font-medium normal-case text-slate-950 focus:border-saints-red focus:outline-none focus:ring-2 focus:ring-saints-red/20" />
                <span className="block text-right text-xs font-semibold text-slate-500">{draft[field].length}/{LIMITS[field]}</span>
              </label>
            ))}
            {changed ? (
              <button type="button" onClick={() => setDraft(original ? { ...original } : null)}
                className="text-sm font-bold text-slate-600 underline underline-offset-4">Discard unsaved changes</button>
            ) : null}
            <button type="button" onClick={() => void save()} disabled={busy || !changed || FIELDS.some((field) => !draft[field].trim())}
              className="min-h-12 w-full rounded-xl bg-saints-red px-4 text-base font-black text-white disabled:bg-slate-300">
              {busy ? "Saving…" : "Save revised clues"}
            </button>
          </div>
        ) : null}
        {message ? <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm font-bold text-emerald-800">{message}</p> : null}
        {error ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm font-bold text-red-800">{error}</p> : null}
      </div>
    </Card>
  );
}
