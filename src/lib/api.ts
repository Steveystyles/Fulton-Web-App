export type Role = "admin" | "mod" | "user";

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
    difficulty: number;
  };
  result: {
    status: "in_progress" | "won" | "lost";
    attemptsUsed: number;
    score: number;
    guesses: WordleGuess[];
    answer: string | null;
  };
  stats: {
    played: number;
    wins: number;
    losses: number;
    points: number;
    currentSolveStreak: number;
    bestSolveStreak: number;
  };
};

export type AdminUser = User & {
  createdAt: string;
  gamesPlayed: number;
  wins: number;
  losses: number;
};

export type AdminOpsStatus = "healthy" | "degraded" | "offline" | "disabled";

export type AdminOpsTest = {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail";
  detail: string;
};

export type AdminOpsPublicProbe = {
  url: string;
  ok: boolean;
  status: number | null;
  responseTimeMs: number;
  resolvedAddresses: string[];
  payload: { ok?: boolean; date?: string; storage?: { ok?: boolean; errorCount?: number } } | null;
  error: string | null;
  checkedAt: string;
};

export type AdminOpsDisk = {
  path: string;
  exists: boolean;
  totalBytes?: number;
  usedBytes?: number;
  freeBytes?: number;
  usedPct?: number;
  mountPoint?: string;
  source?: string;
  fsType?: string;
};

export type AdminOpsContainer = {
  name: string;
  image: string;
  state: string;
  status: string;
  health?: string | null;
  startedAt?: string | null;
  restarts?: number | null;
  ports: string[];
  networks: string[];
  mounts: Array<{
    type?: string | null;
    source?: string | null;
    destination?: string | null;
    rw?: boolean | null;
  }>;
  cpuPct?: number | null;
  memory: {
    usedBytes?: number | null;
    limitBytes?: number | null;
    usedPct?: number | null;
  };
  networkIO: {
    inBytes?: number | null;
    outBytes?: number | null;
  };
  blockIO: {
    inBytes?: number | null;
    outBytes?: number | null;
  };
  pids?: number | null;
};

export type AdminOpsVolume = {
  name: string;
  driver?: string | null;
  mountpoint?: string | null;
  scope?: string | null;
  createdAt?: string | null;
};

export type AdminOpsNetwork = {
  name: string;
  driver?: string | null;
  scope?: string | null;
  builtin?: boolean;
  composeProject?: string | null;
  composeNetwork?: string | null;
  orphaned?: boolean;
  subnets: string[];
  gateways: string[];
  attachedContainers: string[];
};

export type AdminOpsQuizQuestion = {
  subject: "football" | "general_knowledge";
  difficulty: QuizDifficulty;
  question: string;
  choices: string[];
  correctAnswer: string;
  explanation: string;
};

export type AdminOpsQuizPreview = {
  date: string;
  status: string;
  acceptedQuestions: number;
  failedAttempts: number;
  failureReason?: string | null;
  updatedAt?: string | null;
  questions: AdminOpsQuizQuestion[];
};

export type AdminOpsRemoteSnapshot = {
  ok: boolean;
  generatedAt: string;
  responseTimeMs: number;
  host: {
    hostname?: string | null;
    generatedAt: string;
    uptimeSeconds?: number | null;
    loadAverage?: number[] | null;
    cpuCount?: number | null;
    power: {
      acOnline?: boolean | null;
      batteries: Array<{
        name: string;
        status?: string | null;
        capacityPct?: number | string | null;
        energyNow?: number | string | null;
        energyFull?: number | string | null;
        energyFullDesign?: number | string | null;
      }>;
    };
  };
  resources: {
    memory: {
      totalBytes?: number | null;
      availableBytes?: number | null;
      usedBytes?: number | null;
      usedPct?: number | null;
    };
    disks: AdminOpsDisk[];
  };
  docker: {
    containers: AdminOpsContainer[];
    volumes: AdminOpsVolume[];
    networks: AdminOpsNetwork[];
  };
  application: {
    composeFile: string;
    envFile: string;
    dataDir: string;
    dbPath: string;
    health: {
      url: string;
      ok: boolean;
      status?: number | null;
      responseTimeMs?: number | null;
      payload?: { ok?: boolean; date?: string; storage?: { ok?: boolean; errorCount?: number } } | null;
      error?: string | null;
    };
    sqlite: {
      dbPath: string;
      dbExists: boolean;
      dbSizeBytes?: number | null;
      quickCheck?: string | null;
      userCount?: number | null;
      tableCounts: Record<string, number>;
      todayQuiz?: AdminOpsQuizPreview | null;
      tomorrowQuiz?: AdminOpsQuizPreview | null;
    };
  };
  quiz: {
    today?: AdminOpsQuizPreview | null;
    tomorrow?: AdminOpsQuizPreview | null;
  };
  tests: AdminOpsTest[];
  errors: string[];
};

export type AdminOpsSnapshot = {
  enabled: boolean;
  status: AdminOpsStatus;
  ok: boolean;
  generatedAt: string;
  cacheAgeSec: number;
  stale: boolean;
  reason?: string;
  publicProbe: AdminOpsPublicProbe | null;
  remote: AdminOpsRemoteSnapshot | null;
  alerts: string[];
  errors: string[];
  lastError?: string;
};

export type LocalOpsConfig = {
  cacheTtlSec: number;
  sshTarget: string;
  sshPort: number;
  sshKeyPath: string;
  sshConnectTimeoutSec: number;
  publicHealthUrl: string;
  internalBaseUrl: string;
  internalQuizToken: string;
  composeFile: string;
  envFile: string;
  dataDir: string;
  dbPath: string;
  appPort: number;
};

export type LocalOpsConfigResponse = {
  config: LocalOpsConfig;
  settingsPath: string;
};

export type LocalOpsActionName =
  | "generate_tomorrow_quiz"
  | "remove_orphaned_networks"
  | "regenerate_question";

export type LocalOpsActionRequest = {
  action: LocalOpsActionName;
  params?: Record<string, unknown>;
};

export type LocalOpsActionJobStatus = "queued" | "running" | "succeeded" | "failed";

export type LocalOpsActionResponse = {
  action: LocalOpsActionName;
  status: LocalOpsActionJobStatus;
  done: boolean;
  message: string;
  jobId?: string;
  details?: Record<string, unknown>;
  snapshot?: AdminOpsSnapshot;
  error?: string;
  createdAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  reused?: boolean;
};

export type WordleDefinitionEntry = {
  definition: string;
  partOfSpeech: string | null;
};

export type WordleDefinition = {
  word: string;
  definition: string | null;
  partOfSpeech: string | null;
  definitions?: WordleDefinitionEntry[];
  sourceUrl: string;
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

export type DailyQuizResult = {
  date: string;
  category: "football" | "general";
  score: number;
  maxScore: number;
  correctCount: number;
  bonusPoints: number;
  completedAt: string;
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
  category?: "history" | "sport" | "born";
  label?: string;
};

export type LeaderboardPlayer = {
  rank: number;
  id: number;
  username: string;
  weeklyPoints: number;
  weeklyWordlePoints: number;
  weeklyQuizPoints: number;
  totalPoints: number;
  wordlePoints: number;
  weeklyWordleDifficultyBonus: number;
  wordleDifficultyBonus: number;
  wordlePlayed: number;
  wordleWins: number;
  quizPoints: number;
  quizMaxPoints: number;
  quizPlayed: number;
  quizCorrect: number;
  currentStreak: number;
  bestStreak: number;
  wordleLevel: number;
  bestWordleLevel: number;
};

export type LeaderboardResponse = {
  players: LeaderboardPlayer[];
  summary: {
    periodStart: string;
    periodEnd: string;
    playerCount: number;
    weeklyPoints: number;
    totalPoints: number;
    quizPlays: number;
    wordlePlays: number;
    bestStreak: number;
  };
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
  critique?: {
    summary: string;
    relevance: number;
    interestingness: number;
    placeSpecificity: number;
  };
  image?: HistoryLocationImage | null;
};

export type HistoryLocationProfile = {
  title: string;
  types: string[];
  population: string | null;
  areas: string[];
  country: string | null;
  inception: string | null;
  sourceName: string;
  sourceUrl: string | null;
};

export type HistoryLocationImage = {
  url: string;
  title: string;
  sourceName: string;
  sourceUrl: string | null;
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
    profile?: HistoryLocationProfile | null;
    facts: Array<string | HistoryFact>;
    articleUrl: string | null;
    thumbnailUrl: string | null;
    images?: HistoryLocationImage[];
  } | null;
  globalEvents: HistoryEvent[];
  partial: boolean;
  warnings: Array<{ source: string; code: string; detail: string }>;
  meta: {
    cached: boolean;
    eventsLanguage: string;
    generatedAt: string;
    rotationCreatedAt: string | null;
    rotationExpiresAt: string | null;
  };
};

type JsonBody = Record<string, unknown>;

type PublishedQuizQuestion = {
  subject: "football" | "general_knowledge";
  difficulty: QuizDifficulty;
  question: string;
  choices: string[];
  correct_answer: string;
  explanation: string;
};

type PublishedQuizResponse = {
  date: string;
  status: "published";
  questions: PublishedQuizQuestion[];
};

let dailyQuestionsPromise: Promise<DailyQuestionsResponse> | undefined;
const newsPromises = new Map<string, Promise<NewsResponse>>();
const historyPromises = new Map<string, Promise<HistoryResponse>>();

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

function historyCacheKey(params: { location: string; date: string; lang?: string }) {
  return `${params.lang ?? "en"}:${params.location.trim().toLowerCase()}:${params.date}`;
}

function fetchDailyQuestions(options: { force?: boolean } = {}) {
  if (!options.force && dailyQuestionsPromise !== undefined) {
    return dailyQuestionsPromise;
  }

  const promise = request<PublishedQuizResponse>("/api/daily-quiz")
    .then((payload) => {
      const questions: DailyQuestionsResponse = {
        date: payload.date,
        football: [],
        general: [],
      };
      for (const question of payload.questions) {
        const item: DailyQuizQuestion = {
          difficulty: question.difficulty,
          question: question.question,
          answers: question.choices,
          correct_answer: question.correct_answer,
          explanation: question.explanation,
        };
        if (question.subject === "football") {
          questions.football.push(item);
        } else if (question.subject === "general_knowledge") {
          questions.general.push(item);
        }
      }
      return questions;
    })
    .catch((error) => {
      dailyQuestionsPromise = undefined;
      throw error;
    });
  dailyQuestionsPromise = promise;
  return promise;
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
  ).finally(() => {
    if (newsPromises.get(cacheKey) === promise) {
      newsPromises.delete(cacheKey);
    }
  });
  newsPromises.set(cacheKey, promise);
  return promise;
}

function fetchHistory(params: { location: string; date: string; lang?: string }) {
  const cacheKey = historyCacheKey(params);
  const existingPromise = historyPromises.get(cacheKey);
  if (existingPromise !== undefined) {
    return existingPromise;
  }

  const searchParams = new URLSearchParams({
    location: params.location,
    date: params.date,
    lang: params.lang ?? "en",
  });
  const promise = request<HistoryResponse>(`/api/facts?${searchParams.toString()}`).catch(
    (error) => {
      historyPromises.delete(cacheKey);
      throw error;
    },
  );
  historyPromises.set(cacheKey, promise);
  return promise;
}

function todayIsoDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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

  wordleDefinition() {
    return request<WordleDefinition>("/api/wordle/definition");
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

  leaderboard() {
    return request<LeaderboardResponse>("/api/leaderboard");
  },

  dailyQuestions(options?: { force?: boolean }) {
    return fetchDailyQuestions(options);
  },

  submitDailyQuizResult(payload: {
    date: string;
    category: "football" | "general";
    answers: string[];
  }) {
    return request<{ result: DailyQuizResult }>("/api/daily-quiz/result", {
      method: "POST",
      body: jsonBody(payload),
    });
  },

  news(limit = 50, category: NewsCategory = "all", options?: { force?: boolean }) {
    return fetchNews(limit, category, options);
  },

  warmNews() {
    void fetchNews(50, "all").catch(() => undefined);
    void fetchNews(50, "breaking").catch(() => undefined);
    void fetchNews(50, "live-scores").catch(() => undefined);
    void fetchNews(12, "all").catch(() => undefined);
  },

  history(params: { location: string; date: string; lang?: string }) {
    return fetchHistory(params);
  },

  warmHistory(location = "Paisley") {
    void fetchHistory({ location, date: todayIsoDate(), lang: "en" }).catch(() => undefined);
  },

  warmCoreData() {
    this.warmNews();
    this.warmHistory();
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

  adminOpsMonitor(options?: { force?: boolean }) {
    const params = new URLSearchParams();
    if (options?.force) {
      params.set("force", "1");
    }
    const query = params.toString();
    return request<AdminOpsSnapshot>(
      `/api/admin/ops-monitor${query ? `?${query}` : ""}`,
    );
  },

  localOpsMonitor(options?: { force?: boolean }) {
    const params = new URLSearchParams();
    if (options?.force) {
      params.set("force", "1");
    }
    const query = params.toString();
    return request<AdminOpsSnapshot>(
      `/api/local/ops-monitor${query ? `?${query}` : ""}`,
    );
  },

  localOpsConfig() {
    return request<LocalOpsConfigResponse>("/api/local/ops-config");
  },

  updateLocalOpsConfig(payload: LocalOpsConfig) {
    return request<LocalOpsConfigResponse>("/api/local/ops-config", {
      method: "POST",
      body: jsonBody(payload),
    });
  },

  localOpsAction(requestPayload: LocalOpsActionRequest) {
    return request<LocalOpsActionResponse>("/api/local/ops-action", {
      method: "POST",
      body: jsonBody(requestPayload),
    });
  },

  localOpsActionStatus(jobId: string) {
    const params = new URLSearchParams({ jobId });
    return request<LocalOpsActionResponse>(`/api/local/ops-action-status?${params.toString()}`);
  },
};
