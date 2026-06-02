import { FormEvent, useEffect, useState } from "react";
import { KeyRound, Plus, ShieldCheck, Trash2, UsersRound } from "lucide-react";
import { AdminOpsDashboard } from "../components/AdminOpsDashboard";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";
import { useAuth } from "../context/AuthContext";
import { api, type AdminUser, type Role } from "../lib/api";

export function Admin() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [resetPasswords, setResetPasswords] = useState<Record<number, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function loadUsers() {
    setError("");
    const response = await api.adminUsers();
    setUsers(response.users);
  }

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const response = await api.adminUsers();
        if (active) {
          setUsers(response.users);
        }
      } catch (caughtError) {
        if (active) {
          setError(caughtError instanceof Error ? caughtError.message : "Users failed to load.");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      active = false;
    };
  }, []);

  async function handleAddUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    setSaving(true);

    try {
      await api.createUser({ username, password, role });
      setUsername("");
      setPassword("");
      setRole("user");
      await loadUsers();
      setMessage("Player added.");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Player was not added.");
    } finally {
      setSaving(false);
    }
  }

  async function handleResetPassword(targetUser: AdminUser) {
    const nextPassword = resetPasswords[targetUser.id] ?? "";
    setMessage("");
    setError("");

    try {
      await api.resetUserPassword(targetUser.id, nextPassword);
      setResetPasswords((current) => ({ ...current, [targetUser.id]: "" }));
      setMessage(`${targetUser.username} password reset.`);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Password was not reset.");
    }
  }

  async function handleDeleteUser(targetUser: AdminUser) {
    const confirmed = window.confirm(`Delete ${targetUser.username}?`);
    if (!confirmed) {
      return;
    }

    setMessage("");
    setError("");

    try {
      await api.deleteUser(targetUser.id);
      await loadUsers();
      setMessage(`${targetUser.username} deleted.`);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Player was not deleted.");
    }
  }

  return (
    <PageContainer title={isAdmin ? "ADMIN" : "PLAYERS"} number="A">
      {isAdmin ? <AdminOpsDashboard /> : null}

      <Card>
        <form className="space-y-4" onSubmit={handleAddUser}>
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
              <ShieldCheck aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-black leading-tight text-slate-950">Add player</p>
              <p className="mt-1 text-sm font-semibold text-slate-600">
                {isAdmin
                  ? "Create player, moderator, or admin accounts with 12+ character passwords."
                  : "Create a player account and choose their first password."}
              </p>
            </div>
          </div>

          <div className="grid gap-3">
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              placeholder="Username"
              autoComplete="off"
              required
            />
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              placeholder="Password"
              type="password"
              autoComplete="new-password"
              required
            />
            {isAdmin ? (
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
                className="h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              >
                <option value="user">Player</option>
                <option value="mod">Moderator</option>
                <option value="admin">Admin</option>
              </select>
            ) : null}
          </div>

          <button
            type="submit"
            disabled={saving}
            className="flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 text-base font-black text-white shadow-soft transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/30 disabled:cursor-wait disabled:bg-slate-400"
          >
            <Plus aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            {saving ? "Adding" : "Add Player"}
          </button>
        </form>
      </Card>

      <Card>
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-red text-white">
            <UsersRound aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-black leading-tight text-slate-950">Players</p>
            <p className="mt-1 text-sm font-semibold text-slate-600">
              {loading ? "Loading" : `${users.length} account${users.length === 1 ? "" : "s"}`}
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {users.map((targetUser) => {
            const cannotDelete = targetUser.id === user?.id;

            return (
              <article
                key={targetUser.id}
                className="rounded-2xl border border-slate-200 bg-slate-50 p-3"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-saints-black text-sm font-black text-white">
                    {targetUser.username.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-base font-black text-slate-950">
                      {targetUser.username}
                    </p>
                    <p className="mt-1 text-xs font-bold uppercase tracking-normal text-slate-500">
                      {targetUser.role} / {targetUser.gamesPlayed} played / {targetUser.wins} wins
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Delete ${targetUser.username}`}
                    disabled={cannotDelete}
                    onClick={() => void handleDeleteUser(targetUser)}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-saints-red shadow-sm transition hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-saints-red/30 disabled:cursor-not-allowed disabled:text-slate-300"
                  >
                    <Trash2 aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </button>
                </div>

                {isAdmin ? (
                  <div className="mt-3 flex gap-2">
                    <input
                      value={resetPasswords[targetUser.id] ?? ""}
                      onChange={(event) =>
                        setResetPasswords((current) => ({
                          ...current,
                          [targetUser.id]: event.target.value,
                        }))
                      }
                      className="h-11 min-w-0 flex-1 rounded-2xl border border-slate-300 bg-white px-3 text-sm font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
                      placeholder="New password (12+ chars)"
                      type="password"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      aria-label={`Reset ${targetUser.username} password`}
                      onClick={() => void handleResetPassword(targetUser)}
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-slate-500/30"
                    >
                      <KeyRound aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                    </button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
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
