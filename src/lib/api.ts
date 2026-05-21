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

export type QuizDifficulty = "easy" | "medium" | "hard";

export type DailyQuizQuestion = {
  difficulty: QuizDifficulty;
  question: string;
  answers: string[];
  correct_answer: string;
  explanation: string;
};

export type DailyQuestionsResponse = {
  date: string;
  football: DailyQuizQuestion[];
  general: DailyQuizQuestion[];
};

export type NewsItem = {
  id: number;
  sourceKey: string;
  kind: string;
  title: string;
  url: string;
  source: string;
  summary: string;
  publishedAt: string;
  host: string;
  priority: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
};

export type NewsCategory = "all" | "breaking" | "news" | "live-scores";

export type NewsResponse = {
  items: NewsItem[];
  category: NewsCategory;
};

export type HistoryEvent = {
  year: string;
  text: string;
  links: Array<{ title?: string; link?: string }>;
};

export type HistoryFactTheme =
  | "history"
  | "landmark"
  | "industry"
  | "culture"
  | "people"
  | "date"
  | "general";

export type HistoryFact = {
  title: string;
  text: string;
  theme: HistoryFactTheme;
  sourceName: string;
  sourceUrl: string | null;
  confidence: "high" | "medium" | "low";
};

export type HistoryResponse = {
  request: {
    location: string;
    date: string;
    lang: string;
  };
  location: {
    title: string;
    description: string | null;
    facts: Array<string | HistoryFact>;
    articleUrl: string | null;
    thumbnailUrl: string | null;
  } | null;
  globalEvents: HistoryEvent[];
  partial: boolean;
  warnings: Array<{ source: string; code: string; detail: string }>;
  meta: {
    cached: boolean;
    eventsLanguage: string;
    generatedAt: string;
  };
};

type JsonBody = Record<string, unknown>;

let dailyQuestionsPromise: Promise<DailyQuestionsResponse> | undefined;
const newsPromises = new Map<string, Promise<NewsResponse>>();

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

function newsCacheKey(limit: number, category: NewsCategory) {
  return `${category}:${limit}`;
}

function fetchNews(
  limit = 50,
  category: NewsCategory = "all",
  options: { force?: boolean } = {},
) {
  const boundedLimit = Math.max(1, Math.min(100, limit));
  const cacheKey = newsCacheKey(boundedLimit, category);
  const existingPromise = newsPromises.get(cacheKey);

  if (!options.force && existingPromise !== undefined) {
    return existingPromise;
  }

  const promise = request<NewsResponse>(
    `/api/news?limit=${boundedLimit}&category=${category}`,
  ).catch((error) => {
    newsPromises.delete(cacheKey);
    throw error;
  });
  newsPromises.set(cacheKey, promise);
  return promise;
}

function fetchDailyQuestions(options: { force?: boolean } = {}) {
  if (options.force) {
    dailyQuestionsPromise = undefined;
  }

  if (dailyQuestionsPromise === undefined) {
    dailyQuestionsPromise = request<DailyQuestionsResponse>("/api/daily-questions").catch(
      (error) => {
        dailyQuestionsPromise = undefined;
        throw error;
      },
    );
  }

  return dailyQuestionsPromise;
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

  validateWordleGuess(guess: string) {
    return request<{ valid: boolean }>(`/api/wordle/validate/${guess}`);
  },

  submitWordleGuess(guess: string) {
    return request<WordleState>("/api/wordle/guess", {
      method: "POST",
      body: jsonBody({ guess }),
    });
  },

  dailyQuestions(options?: { force?: boolean }) {
    return fetchDailyQuestions(options);
  },

  news(limit = 50, category: NewsCategory = "all", options?: { force?: boolean }) {
    return fetchNews(limit, category, options);
  },

  warmNews() {
    void fetchNews(50, "all").catch(() => undefined);
    void fetchNews(50, "breaking").catch(() => undefined);
    void fetchNews(50, "live-scores").catch(() => undefined);
    void fetchNews(5, "breaking").catch(() => undefined);
  },

  history(params: { location: string; date: string; lang?: string }) {
    const searchParams = new URLSearchParams({
      location: params.location,
      date: params.date,
      lang: params.lang ?? "en",
    });
    return request<HistoryResponse>(`/api/history?${searchParams.toString()}`);
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
