import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../lib/api";

export function Start() {
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    void api.today().then(data => {
      if (!active) return;
      const next = data.activities.find(item => item.status === "continue")
        ?? data.activities.find(item => item.status === "ready");
      setTarget(next?.href ?? "/today");
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Daily games could not be loaded."); });
    return () => { active = false; };
  }, [version]);
  if (target) return <Navigate to={target} replace />;
  return <div className="p-6 text-center"><p role={error ? "alert" : "status"} className="font-bold">{error || "Finding your next game…"}</p>{error ? <button type="button" className="mt-4 min-h-11 rounded-xl border border-slate-300 bg-white px-4 py-2 font-bold saints-focus" onClick={() => setVersion(value => value + 1)}>Try again</button> : null}</div>;
}
