import { Tweet, User, UserRole } from "../types";

const API_URL = "/api";

type ApiError = Error & {
  status?: number;
  responseBody?: unknown;
};
let apiAuthUser: Pick<User, "username" | "role" | "sessionToken"> | null = null;

export const setApiAuthUser = (user: User | null) => {
  apiAuthUser = user
    ? {
        username: user.username,
        role: user.role,
        sessionToken: user.sessionToken,
      }
    : null;
};

const apiRequest = async <T>(
  endpoint: string,
  method: string = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);

  try {
    const options: RequestInit = {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(apiAuthUser?.sessionToken
          ? {
              "X-Username": encodeURIComponent(apiAuthUser.username),
              "X-User-Role": encodeURIComponent(apiAuthUser.role),
              "X-Session-Token": encodeURIComponent(apiAuthUser.sessionToken),
            }
          : {}),
      },
      signal: controller.signal,
    };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_URL}${endpoint}`, options);
    clearTimeout(timeoutId);

    if (!response.ok) {
      let responseBody: unknown;
      try {
        responseBody = await response.json();
      } catch {
        responseBody = await response.text();
      }

      const error = new Error(
        `API Error ${response.status}: ${response.statusText}`,
      ) as ApiError;
      error.status = response.status;
      error.responseBody = responseBody;
      throw error;
    }

    return (await response.json()) as T;
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error.name === "AbortError") {
      throw new Error("Server took too long to respond");
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
};

export type TweetPageQuery = {
  limit?: number;
  cursor?: string;
  assignedTo?: string;
  mistakesFor?: string;
  finalLabel?: string;
  conflictOnly?: boolean;
  round?: number;
  includeModelData?: boolean;
};

export type TweetPageResponse = {
  items: Tweet[];
  nextCursor: string | null;
  hasMore: boolean;
  total?: number;
};

export type TweetRoundsResponse = {
  rounds: number[];
  currentRound: number;
  totalRounds: number;
};

export type CrawlerStatus =
  | "salafi_jihadi"
  | "salafi_taklidi"
  | "not_salafi_jihadi"
  | "insufficient_data";

export type CrawlerModelLabel =
  | "Salafi jihadi"
  | "Salafi taklidi"
  | "Irrelevant";

export type CrawlerScore = {
  positive_count?: number;
  taklidi_count?: number;
  evaluated_count?: number;
  positive_ratio?: number;
  taklidi_ratio?: number;
  profile_positive_count?: number;
  profile_taklidi_count?: number;
  profile_evaluated_count?: number;
};

export type CrawlerThresholds = {
  positive_ratio_threshold?: number;
  taklidi_ratio_threshold?: number;
  taklidi_ratio_margin?: number;
  min_positive_tweets?: number;
  min_profile_evaluated_tweets?: number;
};

export type CrawlerInfluence = {
  location?: string;
  description?: string;
  followers_count?: number | null;
  following_count?: number | null;
  tweet_count?: number | null;
  verified?: boolean;
  views_count?: number;
  likes_count?: number;
  replies_count?: number;
  retweets_count?: number;
  quotes_count?: number;
  bookmarks_count?: number;
  shares_count?: number;
  engagement_count?: number;
  influence_score?: number;
  engagement_source_count?: number;
};

export type CrawlerEvidenceAuthor = {
  id?: string;
  username?: string;
  name?: string;
  location?: string;
  description?: string;
  followers_count?: number | null;
  following_count?: number | null;
  tweet_count?: number | null;
  verified?: boolean;
};

export type CrawlerModelInfo = {
  model_name?: string;
  model_export_dir?: string;
  model_metadata_file?: string;
  model_type?: string;
  experiment_model_type?: string;
  project_id?: number;
  project_name?: string;
  experiment_id?: number;
  experiment_name?: string;
  iteration_id?: number;
  iteration_number?: number;
  iteration?: number;
  export_name?: string;
  labels?: string[];
  max_length?: number;
  prediction_type?: string;
  temperature?: number;
};

export type CrawlerUser = {
  _id?: string;
  username_key: string;
  username: string;
  current_status: CrawlerStatus;
  latest_run_id?: string;
  latest_score?: CrawlerScore;
  latest_influence?: CrawlerInfluence;
  latest_thresholds?: CrawlerThresholds;
  latest_model?: CrawlerModelInfo;
  first_seen_at?: string;
  last_seen_at?: string;
  discovered_by_keywords?: string[];
};

export type CrawlerUserRun = {
  _id?: string;
  run_id: string;
  username_key: string;
  username: string;
  status?: CrawlerStatus;
  score?: CrawlerScore;
  influence?: CrawlerInfluence;
  thresholds?: CrawlerThresholds;
  model?: CrawlerModelInfo;
  created_at?: string;
  trigger_tweet_keys?: string[];
  evidence_tweet_keys?: string[];
};

export type CrawlerRun = {
  _id?: string;
  run_id: string;
  status?: string;
  started_at?: string;
  finished_at?: string;
  keywords?: string[];
  params?: Record<string, unknown>;
  counts?: Record<string, number>;
};

export type CrawlerEvidence = {
  _id?: string;
  run_id?: string;
  username_key: string;
  username: string;
  phase: "keyword_trigger" | "profile_deep_dive" | string;
  tweet_key?: string;
  tweet_id?: string;
  tweet_url?: string;
  text: string;
  model_label?: string;
  flagged?: boolean;
  confidence?: number;
  probabilities?: Record<string, number>;
  source?: {
    created_at?: string;
    like_count?: number;
    retweet_count?: number;
    reply_count?: number;
    quote_count?: number;
    view_count?: number;
    bookmark_count?: number;
    author?: CrawlerEvidenceAuthor;
  };
  format_version?: string;
  is_retweet?: boolean;
  is_quote?: boolean;
  source_text_kind?: string;
  is_merged_thread?: boolean;
  thread_length?: number;
  thread_tweet_ids?: string[];
  collected_at?: string;
  admin_label?: CrawlerModelLabel;
  admin_label_by?: string;
  admin_label_at?: string;
};

export type CrawlerEvidenceAdminStats = {
  labeledByAdmin: number;
  totalWithModelLabel: number;
  matches: number;
  accuracy: number | null;
};

export type CrawlerUserPageResponse = {
  items: CrawlerUser[];
  nextCursor: string | null;
  hasMore: boolean;
  total: number;
  statusCounts?: Record<CrawlerStatus, number>;
};

export type CrawlerRunPageResponse = {
  items: CrawlerRun[];
  nextCursor: string | null;
  hasMore: boolean;
  total: number;
};

export type CrawlerKeywordResponse = {
  items: string[];
  total: number;
};

export type StartCrawlerRunResponse = {
  success: boolean;
  message?: string;
  mode?: "default" | "custom";
  keywordCount?: number;
  error?: string;
};

export type CrawlerEvidencePageResponse = {
  items: CrawlerEvidence[];
  nextCursor: string | null;
  hasMore: boolean;
  total: number;
  labelCounts?: Record<string, number>;
  adminStats?: CrawlerEvidenceAdminStats;
};

export type CrawlerUserQuery = {
  status?: CrawlerStatus | "all";
  runId?: string;
  search?: string;
  limit?: number;
  cursor?: string;
};

export type CrawlerEvidenceQuery = {
  usernameKey: string;
  positiveOnly?: boolean;
  runId?: string;
  label?: CrawlerModelLabel | "all";
  limit?: number;
  cursor?: string;
};

export type TweetDelta = {
  set?: Record<string, unknown>;
  unset?: string[];
  expectedVersion?: number;
};

type BulkDeltaOp = TweetDelta & { tweetId: string };

type PatchTweetResponse = {
  success: boolean;
  tweet: Tweet;
};

type BulkPatchResponse = {
  success: boolean;
  results: Array<{
    success: boolean;
    tweetId?: string;
    error?: string;
    tweet?: Tweet;
  }>;
};

type AnnotateResponse = {
  success: boolean;
  tweetId: string;
  finalLabel?: string;
  version: number;
};

const buildTweetDelta = (tweet: Tweet): TweetDelta => {
  const set: Record<string, unknown> = {};
  const unset: string[] = [];
  const unsettableFields = new Set([
    "finalLabel",
    "resolutionReason",
    "wasInConflict",
    "conflictHistoryDismissed",
    "conflictDetectedAt",
    "conflictResolvedAt",
  ]);

  Object.entries(tweet).forEach(([key, value]) => {
    if (key === "_id" || key === "v") {
      return;
    }
    if (value === undefined || value === null || value === "") {
      if (unsettableFields.has(key)) {
        unset.push(key);
      }
      return;
    }
    set[key] = value;
  });

  return {
    set,
    unset,
    expectedVersion: tweet.v,
  };
};

const buildCrawlerUserParams = (q: CrawlerUserQuery) => {
  const params = new URLSearchParams();
  if (q.status && q.status !== "all") params.set("status", q.status);
  if (q.runId && q.runId !== "all") params.set("runId", q.runId);
  if (q.search) params.set("search", q.search);
  if (q.limit) params.set("limit", String(q.limit));
  if (q.cursor) params.set("cursor", q.cursor);
  return params;
};

const downloadApiFile = async (endpoint: string, filename: string) => {
  const response = await fetch(`${API_URL}${endpoint}`, {
    method: "GET",
    headers: {
      ...(apiAuthUser?.sessionToken
        ? {
            "X-Username": encodeURIComponent(apiAuthUser.username),
            "X-User-Role": encodeURIComponent(apiAuthUser.role),
            "X-Session-Token": encodeURIComponent(apiAuthUser.sessionToken),
          }
        : {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Export failed: ${response.status} ${response.statusText}`);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

export const getTweetPage = async (
  q: TweetPageQuery,
  signal?: AbortSignal,
): Promise<TweetPageResponse> => {
  const params = new URLSearchParams();
  if (q.limit) params.set("limit", String(q.limit));
  if (q.cursor) params.set("cursor", q.cursor);
  if (q.assignedTo) params.set("assignedTo", q.assignedTo);
  if (q.mistakesFor) params.set("mistakesFor", q.mistakesFor);
  if (q.finalLabel) params.set("finalLabel", q.finalLabel);
  if (q.conflictOnly) params.set("conflictOnly", "true");
  if (q.round !== undefined) params.set("round", String(q.round));
  if (q.includeModelData) params.set("includeModelData", "true");

  return apiRequest<TweetPageResponse>(
    `/tweets${params.toString() ? `?${params.toString()}` : ""}`,
    "GET",
    undefined,
    signal,
  );
};

export const getTweetRounds = async (
  signal?: AbortSignal,
): Promise<TweetRoundsResponse> => {
  return apiRequest<TweetRoundsResponse>("/tweets/rounds", "GET", undefined, signal);
};

export const getCrawlerUsers = async (
  q: CrawlerUserQuery,
  signal?: AbortSignal,
): Promise<CrawlerUserPageResponse> => {
  const params = buildCrawlerUserParams(q);
  return apiRequest<CrawlerUserPageResponse>(
    `/crawler/users${params.toString() ? `?${params.toString()}` : ""}`,
    "GET",
    undefined,
    signal,
  );
};

export const getCrawlerEvidence = async (
  q: CrawlerEvidenceQuery,
  signal?: AbortSignal,
): Promise<CrawlerEvidencePageResponse> => {
  const params = new URLSearchParams();
  if (q.positiveOnly) params.set("positiveOnly", "true");
  if (q.runId && q.runId !== "all") params.set("runId", q.runId);
  if (q.label && q.label !== "all") params.set("label", q.label);
  if (q.limit) params.set("limit", String(q.limit));
  if (q.cursor) params.set("cursor", q.cursor);
  return apiRequest<CrawlerEvidencePageResponse>(
    `/crawler/users/${encodeURIComponent(q.usernameKey)}/evidence${
      params.toString() ? `?${params.toString()}` : ""
    }`,
    "GET",
    undefined,
    signal,
  );
};

export const getCrawlerRuns = async (
  signal?: AbortSignal,
): Promise<CrawlerRunPageResponse> => {
  return apiRequest<CrawlerRunPageResponse>(
    "/crawler/runs?limit=200",
    "GET",
    undefined,
    signal,
  );
};

export const getCrawlerKeywords = async (
  signal?: AbortSignal,
): Promise<CrawlerKeywordResponse> => {
  return apiRequest<CrawlerKeywordResponse>(
    "/crawler/keywords",
    "GET",
    undefined,
    signal,
  );
};

export const saveCrawlerKeywords = async (
  keywords: string[],
): Promise<CrawlerKeywordResponse & { success: boolean }> => {
  return apiRequest<CrawlerKeywordResponse & { success: boolean }>(
    "/crawler/keywords",
    "PUT",
    { keywords },
  );
};

export const startCrawlerRun = async (
  payload: { useDefaultKeywords: boolean; keywords?: string[] },
): Promise<StartCrawlerRunResponse> => {
  return apiRequest<StartCrawlerRunResponse>(
    "/crawler/runs",
    "POST",
    payload,
  );
};

export const setCrawlerEvidenceAdminLabel = async (
  evidenceId: string,
  adminLabel: CrawlerModelLabel | null,
): Promise<{
  success: boolean;
  item?: CrawlerEvidence;
  adminStats?: CrawlerEvidenceAdminStats;
  error?: string;
}> => {
  return apiRequest(
    `/crawler/evidence/${encodeURIComponent(evidenceId)}/admin-label`,
    "PATCH",
    { adminLabel },
  );
};

export const getCrawlerUserRuns = async (
  usernameKey: string,
  signal?: AbortSignal,
): Promise<{ items: CrawlerUserRun[] }> => {
  return apiRequest<{ items: CrawlerUserRun[] }>(
    `/crawler/users/${encodeURIComponent(usernameKey)}/runs`,
    "GET",
    undefined,
    signal,
  );
};

export const exportCrawlerUsersCsv = async (
  q: Pick<CrawlerUserQuery, "status" | "runId" | "search">,
) => {
  const params = buildCrawlerUserParams(q);
  await downloadApiFile(
    `/crawler/export/users.csv${params.toString() ? `?${params.toString()}` : ""}`,
    `crawler_users_${new Date().toISOString().slice(0, 10)}.csv`,
  );
};

export const exportCrawlerEvidenceCsv = async (
  usernameKey: string,
  filters: { positiveOnly?: boolean; runId?: string; label?: CrawlerModelLabel | "all" } = {},
) => {
  const params = new URLSearchParams({ usernameKey });
  if (filters.positiveOnly) params.set("positiveOnly", "true");
  if (filters.runId && filters.runId !== "all") params.set("runId", filters.runId);
  if (filters.label && filters.label !== "all") params.set("label", filters.label);
  await downloadApiFile(
    `/crawler/export/evidence.csv?${params.toString()}`,
    `crawler_evidence_${usernameKey}_${new Date().toISOString().slice(0, 10)}.csv`,
  );
};

export const patchTweetDelta = async (
  tweetId: string,
  delta: TweetDelta,
): Promise<PatchTweetResponse> => {
  return apiRequest<PatchTweetResponse>(`/tweets/${tweetId}`, "PATCH", delta);
};

export const patchTweetsBulk = async (
  ops: BulkDeltaOp[],
): Promise<BulkPatchResponse> => {
  return apiRequest<BulkPatchResponse>("/tweets/delta/bulk", "POST", { ops });
};

export const getTweets = async (signal?: AbortSignal): Promise<Tweet[]> => {
  const allTweets: Tweet[] = [];
  let cursor: string | undefined;
  let hasMore = true;

  while (hasMore) {
    const page = await getTweetPage({ limit: 200, cursor }, signal);
    allTweets.push(...page.items);
    cursor = page.nextCursor ?? undefined;
    hasMore = page.hasMore;
  }

  return allTweets;
};

export const saveTweet = async (tweet: Tweet): Promise<Tweet> => {
  const response = await patchTweetDelta(tweet.id, buildTweetDelta(tweet));
  return response.tweet;
};

export const updateTweets = async (updatedTweetsList: Tweet[]): Promise<Tweet[]> => {
  const response = await patchTweetsBulk(
    updatedTweetsList.map((tweet) => ({
      tweetId: tweet.id,
      ...buildTweetDelta(tweet),
    })),
  );

  const failed = response.results.find((result) => !result.success);
  if (failed) {
    throw new Error(failed.error || "Bulk update failed");
  }

  return response.results
    .map((result) => result.tweet)
    .filter((tweet): tweet is Tweet => Boolean(tweet));
};

export const addTweets = async (newTweets: Tweet[]): Promise<void> => {
  await apiRequest("/tweets/add", "POST", newTweets);
};

export const deleteTweet = async (tweetId: string): Promise<void> => {
  await apiRequest(`/tweet/${tweetId}`, "DELETE");
};

export const deleteAllTweets = async (): Promise<void> => {
  await apiRequest("/tweets", "DELETE");
};

export const getUsers = async (signal?: AbortSignal): Promise<User[]> => {
  const data = await apiRequest<{ users: User[] }>("/users", "GET", undefined, signal);
  return data.users || [];
};

export const getAllStudents = async (): Promise<string[]> => {
  const users = await getUsers();
  return users
    .filter((u) => u.role === UserRole.Student)
    .map((u) => u.username);
};

export const authenticateUser = async (
  username: string,
  password: string,
): Promise<User | null> => {
  try {
    return await apiRequest<User | null>("/users/login", "POST", { username, password });
  } catch (error: any) {
    if (error.status === 401 || error.status === 404) {
      return null;
    }
    throw error;
  }
};

export const registerUser = async (user: User): Promise<User> => {
  try {
    return await apiRequest<User>("/users/register", "POST", user);
  } catch (error) {
    throw new Error("שם המשתמש כבר קיים או שיש בעיית תקשורת");
  }
};

export const changePassword = async (
  username: string,
  currentPassword: string,
  newPassword: string,
): Promise<{ success: boolean; message?: string; error?: string }> => {
  try {
    return await apiRequest("/users/change-password", "POST", {
      username,
      currentPassword,
      newPassword,
    });
  } catch (error) {
    throw new Error("שגיאה בשינוי הסיסמה");
  }
};

export const exportToCSV = (tweets: Tweet[], users: string[]) => {
  const header = ["Tweet ID", "Text", "Final Decision", "Assigned To"];
  users.forEach((u) => {
    header.push(`Label_${u}`);
    header.push(`Reasons_${u}`);
  });

  const rows = tweets.map((tweet) => {
    const assignedStr = tweet.assignedTo ? tweet.assignedTo.join(";") : "";
    const finalLabel =
      tweet.finalLabel === "CONFLICT"
        ? "CONFLICT (Unresolved)"
        : tweet.finalLabel || "";

    const row = [
      tweet.id,
      `"${tweet.text.replace(/"/g, '""')}"`,
      `"${finalLabel}"`,
      `"${assignedStr}"`,
    ];

    users.forEach((u) => {
      const label = tweet.annotations[u] || "";
      const features = tweet.annotationFeatures?.[u]?.join("; ") || "";
      row.push(`"${label}"`);
      row.push(`"${features}"`);
    });

    return row.join(",");
  });

  const csvContent = "\uFEFF" + [header.join(","), ...rows].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute(
    "download",
    `tweets_labels_detailed_${new Date().toISOString().slice(0, 10)}.csv`,
  );
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export const saveAnnotation = async (
  tweetId: string,
  username: string,
  label: string,
  features: string[],
): Promise<AnnotateResponse> => {
  return apiRequest<AnnotateResponse>("/tweet/annotate", "POST", {
    tweetId,
    username,
    label,
    features,
    timestamp: Date.now(),
  });
};
