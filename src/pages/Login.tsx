import { FormEvent, useState } from "react";
import { LogIn, ShieldCheck } from "lucide-react";
import crestPlaceholder from "../assets/crest-placeholder.svg";
import { useAuth } from "../context/AuthContext";

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await login(username, password);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="saints-shell-bg min-h-dvh overflow-x-hidden text-slate-950">
      <main className="mx-auto flex min-h-dvh w-screen max-w-[430px] flex-col justify-center overflow-x-hidden bg-saints-paper px-4 py-8 shadow-2xl ring-1 ring-white/10">
        <section className="max-w-full overflow-hidden rounded-[1.75rem] saints-card p-5">
          <div className="flex items-center gap-3">
            <img
              src={crestPlaceholder}
              alt=""
              className="h-14 w-12 shrink-0"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <p className="truncate text-2xl font-black text-slate-950">
                Fulton's Quiz
              </p>
              <p className="mt-1 text-sm font-bold uppercase tracking-normal text-saints-red">
                Login
              </p>
            </div>
          </div>

          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <label className="block">
              <span className="text-sm font-black uppercase tracking-normal text-slate-600">
                Username
              </span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-2 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
                autoComplete="username"
                required
              />
            </label>

            <label className="block">
              <span className="text-sm font-black uppercase tracking-normal text-slate-600">
                Password
              </span>
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-2 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>

            {error ? (
              <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
                {error}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={submitting}
              className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 py-3 text-base font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30 disabled:cursor-wait disabled:bg-slate-400"
            >
              <LogIn aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
              {submitting ? "Signing in" : "Sign in"}
            </button>
          </form>

          <div className="mt-5 flex items-start gap-3 rounded-2xl bg-slate-50 p-3 text-sm font-bold leading-relaxed text-slate-600">
            <ShieldCheck
              aria-hidden="true"
              className="mt-0.5 h-5 w-5 shrink-0 text-saints-red"
              strokeWidth={2.4}
            />
            <p className="min-w-0">
              Sign in with the account created for you by an administrator.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
