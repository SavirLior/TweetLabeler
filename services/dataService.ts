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
