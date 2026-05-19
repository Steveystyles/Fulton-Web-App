export type Role = "admin" | "user";

export type User = {
  id: number;
  username: string;
  role: Role;
};

export type FeedbackColor = "green" | "yellow" | "grey";

export type FeedbackTile = {
  letter: string;
  color: FeedbackColor;
};

export type WordleGuess = {
  attemptNumber: number;
  guess: string;
  feedback: FeedbackTile[];
};

export type WordleState = {
  game: {
    date: string;
    wordLength: number;
    maxAttempts: number;
  };
  result: {
    status: "in_progress" | "won" | "lost";
    attemptsUsed: number;
    guesses: WordleGuess[];
    answer: string | null;
  };
  stats: {
    played: number;
    wins: number;
    losses: number;
  };
};

export type AdminUser = User & {
  createdAt: string;
  gamesPlayed: number;
  wins: number;
  losses: number;
};

type JsonBody = Record<string, unknown>;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);

  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers,
  });
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      data !== null && typeof data.error === "string"
        ? data.error
        : "Request failed.";
    throw new ApiError(message, response.status);
  }

  return data as T;
}

function jsonBody(body: JsonBody): string {
  return JSON.stringify(body);
}

export const api = {
  me() {
    return request<{ user: User }>("/api/auth/me");
  },

  login(username: string, password: string) {
    return request<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: jsonBody({ username, password }),
    });
  },

  logout() {
    return request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
  },

  updateMe(payload: {
    username?: string;
    currentPassword?: string;
    newPassword?: string;
  }) {
    return request<{ user: User }>("/api/me", {
      method: "PATCH",
      body: jsonBody(payload),
    });
  },

  wordleToday() {
    return request<WordleState>("/api/wordle/today");
  },

  submitWordleGuess(guess: string) {
    return request<WordleState>("/api/wordle/guess", {
      method: "POST",
      body: jsonBody({ guess }),
    });
  },

  adminUsers() {
    return request<{ users: AdminUser[] }>("/api/admin/users");
  },

  createUser(payload: { username: string; password: string; role: Role }) {
    return request<{ ok: boolean }>("/api/admin/users", {
      method: "POST",
      body: jsonBody(payload),
    });
  },

  resetUserPassword(userId: number, password: string) {
    return request<{ ok: boolean }>(`/api/admin/users/${userId}/reset-password`, {
      method: "POST",
      body: jsonBody({ password }),
    });
  },

  deleteUser(userId: number) {
    return request<{ ok: boolean }>(`/api/admin/users/${userId}`, {
      method: "DELETE",
    });
  },
};
