export type Role = "admin" | "mod" | "user";

export type ActivityId = "wordle" | "quiz" | "map";
export type TodayResponse = {
  date: string; nextRoundAt: string;
  nextMapDates: string[];
  activities: Array<{ id: ActivityId; title: string; href: string; status: "ready" | "continue" | "completed" | "unavailable"; score: number | null }>;
};
export type LeaguePlayer = {
  id: number; username: string; rank: number | null; points: number; games: Record<ActivityId, number>;
};
export type LeagueResponse = {
  periodStart: string; periodEnd: string; scoringVersion: string; players: LeaguePlayer[];
  previousWinners: LeaguePlayer[]; previousPeriodEnd: string;
};

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
  internalQuizTokenConfigured: boolean;
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

export type DailyQuizChoice = {
  id: string;
  text: string;
};

export type DailyQuizQuestion = {
  id: string;
  difficulty: QuizDifficulty;
  question: string;
  answers: DailyQuizChoice[];
};

export type DailyQuizSelection = {
  questionId: string;
  choiceId: string;
};

export type DailyQuizAdjudication = DailyQuizSelection & {
  correct: boolean;
  correctChoiceId: string;
  correctAnswer: string;
  explanation: string;
  interestingReason?: string;
  pointsAwarded: number;
};

export type DailyQuestionsResponse = {
  date: string;
  results: Partial<Record<"football" | "general", DailyQuizResult>>;
  progress: Partial<Record<"football" | "general", DailyQuizSelection[]>>;
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
  quizVersion: string;
  scoringVersion: string;
  adjudications: DailyQuizAdjudication[];
  completedAt: string;
};

export type QuizBoardCard = {
  id: string; subject: "football" | "general"; difficulty: QuizDifficulty;
  points: number; teaser: string; source: "new" | "carry" | "practice";
  appearances: number; selectedOrder: number | null; answered: boolean;
  question?: DailyQuizQuestion;
};
export type QuizBoard = {
  date: string; mode: "daily" | "practice"; status: "ready" | "in_progress" | "completed";
  pickCount: number; selectedCount: number; answeredCount: number; score: number;
  maxScore: number; correctCount: number; bonusPoints: number; completedAt: string | null;
  cards: QuizBoardCard[];
};
export type QuizCardAdjudication = {
  cardId: string; correct: boolean; correctAnswer: string; explanation: string;
  interestingReason?: string; pointsAwarded: number;
};
export type AdminProductReport = {
  periodStart: string; periodEnd: string;
  quiz: { started: number; completed: number; completionRate: number; averageScore: number };
  cards: Array<{ subject: string; difficulty: string; answers: number; correct: number }>;
  feedback: Array<{ game: string; rating: string; count: number }>;
  journey: Array<{ game: string; started: number; completed: number; abandoned: number; completionRate: number }>;
  reserve: { cards: number; launchTarget: number };
};

export type Announcement = {
  id: string;
  kind: "daily-map-promo";
};

export type AuthResponse = {
  user: User;
  availableAnnouncements: Announcement[];
  pendingAnnouncements: Announcement[];
};

export type MapPoint = {
  lat: number;
  lng: number;
};

export type DailyMapGameResult = {
  guessedPoint: MapPoint;
  answerPoint: MapPoint;
  distanceMeters: number;
  distanceKm: number;
  distanceFromCentreMeters: number;
  gradedDistanceMeters: number;
  gradedDistanceKm: number;
  targetRadiusMeters: number;
  insideTargetArea: boolean;
  correct: boolean;
  revealedHintCount: number;
  score: number;
  maxPoints: number;
  band: string;
  completedAt: string;
  selectedPlace: {
    name: string | null;
  };
  place: {
    name: string;
    countryCode: string;
    admin1: string | null;
    revealText: string;
  };
};

export type DailyMapClue = {
  id: "hard" | "medium" | "easy" | "name";
  title: string;
  text: string;
  maxPoints: number;
  revealsName?: boolean;
};

export type DailyMapAnchor = {
  name: string;
  point: MapPoint;
  minHintCount: number;
  minZoom: number;
  maxZoom: number;
  boundary?: {
    type: "Polygon" | "MultiPolygon";
    coordinates: unknown;
  };
  boundaryKind?: "administrative" | "guidance";
  boundaryMinZoom?: number;
};

export type DailyMapGameLevel = {
  id: number;
  slug: QuizDifficulty;
  title: string;
  clues: DailyMapClue[];
  mapAnchors: DailyMapAnchor[];
  revealedHintCount: number;
  submitted: boolean;
  result?: DailyMapGameResult;
};

export type DailyMapGameResponse = {
  date: string;
  status: "published";
  maxScore: number;
  completedLevels: number;
  levels: DailyMapGameLevel[];
};

export type DailyMapSnapOption = {
  selectionId: string;
  point: MapPoint;
  clickedPoint: MapPoint;
  snapped: boolean;
  name: string;
  kind: string;
  distanceMeters: number;
  snapRadiusMeters: number;
  countryCode: string | null;
  admin1: string | null;
};

export type DailyMapSnapSelection = DailyMapSnapOption & {
  alternatives?: DailyMapSnapOption[];
  selectedIndex?: number;
};

export type LeaderboardPlayer = {
  rank: number;
  id: number;
  username: string;
  weeklyPoints: number;
  weeklyWordlePoints: number;
  weeklyQuizPoints: number;
  weeklyMapPoints: number;
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
  mapPoints: number;
  mapPlayed: number;
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
    mapPlays: number;
    bestStreak: number;
  };
};

type JsonBody = Record<string, unknown>;

type PublishedQuizQuestion = {
  id: string;
  subject: "football" | "general_knowledge";
  difficulty: QuizDifficulty;
  question: string;
  choices: DailyQuizChoice[];
};

type PublishedQuizResponse = {
  date: string;
  results?: DailyQuestionsResponse["results"];
  progress?: DailyQuestionsResponse["progress"];
  status: "published";
  questions: PublishedQuizQuestion[];
};

let dailyQuestionsPromise: Promise<DailyQuestionsResponse> | undefined;

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

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, 45000);
  try {
  const response = await fetch(path, {
    ...init,
    signal: controller.signal,
    credentials: init.credentials ?? "include",
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
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError("The connection timed out or was interrupted. Your action may have saved; refresh to check before retrying.", 408);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

let cachedLocalOpsToken: string | undefined;

function localOpsAccessToken(): string {
  if (cachedLocalOpsToken !== undefined) {
    return cachedLocalOpsToken;
  }
  if (typeof window === "undefined") {
    return "";
  }
  const fragment = window.location.hash.replace(/^#/, "");
  cachedLocalOpsToken = new URLSearchParams(fragment).get("opsToken")?.trim() ?? "";
  if (cachedLocalOpsToken) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }
  return cachedLocalOpsToken;
}

function localOpsRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = localOpsAccessToken();
  if (!token) {
    return Promise.reject(new ApiError("Open Local Ops using its secure launcher.", 403));
  }
  const headers = new Headers(init.headers);
  headers.set("X-Fultons-Ops-Token", token);
  return request<T>(path, { ...init, credentials: "omit", headers });
}

function jsonBody(body: JsonBody): string {
  return JSON.stringify(body);
}

function fetchDailyQuestions(options: { force?: boolean } = {}) {
  if (!options.force && dailyQuestionsPromise !== undefined) {
    return dailyQuestionsPromise;
  }

  const promise = request<PublishedQuizResponse>("/api/daily-quiz")
    .then((payload) => {
      const questions: DailyQuestionsResponse = {
        date: payload.date,
        results: payload.results ?? {},
        progress: payload.progress ?? {},
        football: [],
        general: [],
      };
      for (const question of payload.questions) {
        const item: DailyQuizQuestion = {
          id: question.id,
          difficulty: question.difficulty,
          question: question.question,
          answers: question.choices,
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

export const api = {
  me() {
    return request<AuthResponse>("/api/auth/me");
  },

  login(username: string, password: string) {
    dailyQuestionsPromise = undefined;
    return request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: jsonBody({ username, password }),
    });
  },

  logout() {
    dailyQuestionsPromise = undefined;
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

  startWordle() {
    return request<WordleState>("/api/wordle/today", { method: "POST" });
  },

  wordleDefinition() {
    return request<WordleDefinition>("/api/wordle/definition");
  },

  validateWordleGuess(guess: string) {
    return request<{ valid: boolean }>(`/api/wordle/validate/${guess}`);
  },

  submitWordleGuess(payload: {
    guess: string;
    expectedAttemptsUsed: number;
    expectedGameDate: string;
  }) {
    return request<WordleState>("/api/wordle/guess", {
      method: "POST",
      body: jsonBody({ ...payload }),
    });
  },

  leaderboard() {
    return request<LeaderboardResponse>("/api/leaderboard");
  },

  dailyQuestions(options?: { force?: boolean }) {
    return fetchDailyQuestions(options);
  },

  quizBoard(mode: "daily" | "practice") {
    return request<QuizBoard>(`/api/quiz/board?mode=${mode}`);
  },
  selectQuizCard(mode: "daily" | "practice", cardId: string) {
    return request<QuizBoard>("/api/quiz/board/select", { method: "POST", body: jsonBody({ mode, cardId }) });
  },
  answerQuizCard(mode: "daily" | "practice", cardId: string, choiceId: string) {
    return request<{ board: QuizBoard; adjudication: QuizCardAdjudication }>("/api/quiz/board/answer", { method: "POST", body: jsonBody({ mode, cardId, choiceId }) });
  },
  feedback(game: "quiz" | "map", rating: "fun" | "fair" | "too_hard" | "unclear") {
    return request<{ ok: boolean }>("/api/feedback", { method: "POST", body: jsonBody({ game, rating }) });
  },
  adminProductReport() {
    return request<AdminProductReport>("/api/admin/product-report");
  },

  today() {
    return request<TodayResponse>("/api/today");
  },

  practiceDates() { return request<{ dates: string[] }>("/api/practice/quizzes"); },
  async practiceQuiz(date: string): Promise<DailyQuestionsResponse> {
    const payload = await request<PublishedQuizResponse>(`/api/practice/quiz?date=${encodeURIComponent(date)}`);
    const convert = (subject: string) => payload.questions.filter(question => question.subject === subject)
      .map(question => ({ id: question.id, question: question.question, difficulty: question.difficulty, answers: question.choices }));
    return { date: payload.date, results: {}, progress: {}, football: convert("football"), general: convert("general_knowledge") };
  },
  submitPracticeQuiz(payload: { date: string; category: "football" | "general"; answers: DailyQuizSelection[] }) {
    return request<{ result: DailyQuizResult }>("/api/practice/quiz/result", { method: "POST", body: jsonBody(payload) });
  },

  league() {
    return request<LeagueResponse>("/api/league");
  },

  saveQuizProgress(payload: { date: string; category: "football" | "general"; answers: DailyQuizSelection[] }) {
    dailyQuestionsPromise = undefined;
    return request<{ answers: DailyQuizSelection[]; result?: DailyQuizResult }>("/api/daily-quiz/progress", {
      method: "POST", body: jsonBody(payload),
    });
  },

  submitDailyQuizResult(payload: {
    date: string;
    category: "football" | "general";
    answers: DailyQuizSelection[];
  }) {
    return request<{ result: DailyQuizResult }>("/api/daily-quiz/result", {
      method: "POST",
      body: jsonBody(payload),
    });
  },

  acknowledgeAnnouncement(campaignId: string, action: "played" | "dismissed") {
    return request<{ ok: boolean }>(
      `/api/announcements/${encodeURIComponent(campaignId)}/acknowledge`,
      {
        method: "POST",
        body: jsonBody({ action }),
      },
    );
  },

  dailyMapGame(date?: string) {
    const query = date ? `?date=${encodeURIComponent(date)}` : "";
    return request<DailyMapGameResponse>(`/api/daily-map-game${query}`);
  },

  snapDailyMapGuess(levelId: number, point: MapPoint, zoom?: number) {
    return request<DailyMapSnapSelection>(`/api/daily-map-game/${levelId}/snap`, {
      method: "POST",
      body: jsonBody({ ...point, zoom }),
    });
  },

  revealDailyMapClue(levelId: number, expectedRevealedHintCount: number) {
    return request<{ level: DailyMapGameLevel }>(
      `/api/daily-map-game/${levelId}/reveal`,
      {
        method: "POST",
        body: jsonBody({ expectedRevealedHintCount }),
      },
    );
  },

  submitDailyMapGuess(levelId: number, selectionId: string) {
    return request<{ result: DailyMapGameResult }>(`/api/daily-map-game/${levelId}/guess`, {
      method: "POST",
      body: jsonBody({ selectionId }),
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

  localOpsMonitor(options?: { force?: boolean }) {
    const params = new URLSearchParams();
    if (options?.force) {
      params.set("force", "1");
    }
    const query = params.toString();
    return localOpsRequest<AdminOpsSnapshot>(
      `/api/local/ops-monitor${query ? `?${query}` : ""}`,
    );
  },

  localOpsConfig() {
    return localOpsRequest<LocalOpsConfigResponse>("/api/local/ops-config");
  },

  updateLocalOpsConfig(payload: LocalOpsConfig) {
    return localOpsRequest<LocalOpsConfigResponse>("/api/local/ops-config", {
      method: "POST",
      body: jsonBody(payload),
    });
  },

  localOpsAction(requestPayload: LocalOpsActionRequest) {
    return localOpsRequest<LocalOpsActionResponse>("/api/local/ops-action", {
      method: "POST",
      body: jsonBody(requestPayload),
    });
  },

  localOpsActionStatus(jobId: string) {
    const params = new URLSearchParams({ jobId });
    return localOpsRequest<LocalOpsActionResponse>(
      `/api/local/ops-action-status?${params.toString()}`,
    );
  },
};
