import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../lib/api";

export function Start() {
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api.today().then(data => {
      if (!active) return;
      const next = data.activities.find(item => item.status === "continue")
        ?? data.activities.find(item => item.status === "ready");
      setTarget(next?.href ?? "/scores");
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Daily games could not be loaded."); });
    return () => { active = false; };
  }, []);
  if (target) return <Navigate to={target} replace />;
  return <div className="p-6 text-center"><p role={error ? "alert" : "status"} className="font-bold">{error || "Finding your next game…"}</p></div>;
}
