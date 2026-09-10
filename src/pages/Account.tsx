import { FormEvent, useState } from "react";
import { KeyRound, Save, UserRound } from "lucide-react";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

export function Account() {
  const [largeText, setLargeText] = useState(() => { try { return localStorage.getItem("fultons-wordle-large-print") === "1"; } catch { return false; } });
  const [sound, setSound] = useState(() => { try { return localStorage.getItem("fultons-wordle-sound") === "1"; } catch { return false; } });
  const { updateUser, user } = useAuth();
  const [username, setUsername] = useState(user?.username ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const accountLabel =
    user?.role === "admin" ? "Admin" : user?.role === "mod" ? "Moderator" : "Player";

  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    setSavingProfile(true);

    try {
      const response = await api.updateMe({ username });
      updateUser(response.user);
      setMessage("Username updated.");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Update failed.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    setSavingPassword(true);

    try {
      const response = await api.updateMe({ currentPassword, newPassword });
      updateUser(response.user);
      setCurrentPassword("");
      setNewPassword("");
      setMessage("Password updated.");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Update failed.");
    } finally {
      setSavingPassword(false);
    }
  }

  return (
    <PageContainer title="ACCOUNT" number="A">
      <Card>
        <form className="space-y-4" onSubmit={handleProfileSubmit}>
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
              <UserRound aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-black leading-tight text-slate-950">Profile</p>
              <p className="mt-1 text-sm font-semibold text-slate-600">
                {accountLabel}
              </p>
            </div>
          </div>

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

          <button
            type="submit"
            disabled={savingProfile || username.trim() === user?.username}
            className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 text-base font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <Save aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            {savingProfile ? "Saving" : "Save Username"}
          </button>
        </form>
      </Card>

      <Card>
        <form className="space-y-4" onSubmit={handlePasswordSubmit}>
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-red text-white">
              <KeyRound aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-black leading-tight text-slate-950">Password</p>
              <p className="mt-1 text-sm font-semibold text-slate-600">
                Change your login password. Use at least 12 characters.
              </p>
            </div>
          </div>

          <label className="block">
            <span className="text-sm font-black uppercase tracking-normal text-slate-600">
              Current
            </span>
            <input
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              className="mt-2 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>

          <label className="block">
            <span className="text-sm font-black uppercase tracking-normal text-slate-600">
              New
            </span>
            <input
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="mt-2 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              type="password"
              autoComplete="new-password"
              required
            />
          </label>

          <button
            type="submit"
            disabled={savingPassword}
            className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 text-base font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30 disabled:cursor-wait disabled:bg-slate-400"
          >
            <Save aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            {savingPassword ? "Saving" : "Save Password"}
          </button>
        </form>
      </Card>

      <Card><h2 className="text-xl font-black">Play preferences</h2><p className="mt-2 text-sm text-slate-600">Saved on this browser. You can also change these inside Wordle. Animations respect your device's reduced-motion setting.</p>
        <label className="mt-3 flex min-h-12 items-center justify-between gap-3 font-bold">Large Wordle text<input type="checkbox" checked={largeText} onChange={event => { setLargeText(event.target.checked); try { localStorage.setItem("fultons-wordle-large-print", event.target.checked ? "1" : "0"); } catch { setError("This browser could not save the preference."); } }} className="h-5 w-5 accent-red-600" /></label>
        <label className="flex min-h-12 items-center justify-between gap-3 font-bold">Wordle sound<input type="checkbox" checked={sound} onChange={event => { setSound(event.target.checked); try { localStorage.setItem("fultons-wordle-sound", event.target.checked ? "1" : "0"); } catch { setError("This browser could not save the preference."); } }} className="h-5 w-5 accent-red-600" /></label>
        <p className="mt-3 text-sm text-slate-600">Need help accessing your account? Contact the administrator who invited you. Never share your password.</p>
      </Card>

      {message ? (
        <p className="rounded-2xl bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-700">
          {message}
        </p>
      ) : null}

      {error ? (
        <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
          {error}
        </p>
      ) : null}
    </PageContainer>
  );
}
