import { Tweet, User, UserRole } from "../types";

const API_URL = "/api";
const DEFAULT_TIMEOUT_MS = 5000;

export type TweetPageQuery = {
  limit?: number;
  cursor?: string;
  assignedTo?: string;
  finalLabel?: string;
  conflictOnly?: boolean;
};

export type TweetPageResponse = {
  items: Tweet[];
  nextCursor: string | null;
  hasMore: boolean;
  total?: number;
};

export type TweetDelta = {
  set?: Record<string, unknown>;
  unset?: string[];
  expectedVersion?: number;
};

export type PatchTweetResponse = {
  success: boolean;
  tweet: Tweet;
};

export type BulkDeltaOperation = {
  tweetId: string;
  set?: Record<string, unknown>;
  unset?: string[];
  expectedVersion?: number;
};

export type BulkDeltaResponse = {
  success: boolean;
  results: Array<{
    tweetId?: string;
    success: boolean;
    version?: number;
    code?: number;
    error?: string;
  }>;
};

export type SaveAnnotationResponse = {
  success: boolean;
  message?: string;
  tweetId: string;
  finalLabel?: string | null;
  version?: number;
};

const apiRequest = async (
  endpoint: string,
  method: string = "GET",
  body?: unknown,
  signal?: AbortSignal
) => {
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, DEFAULT_TIMEOUT_MS);

  const abortByParent = () => controller.abort();
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener("abort", abortByParent);
    }
  }

  try {
    const options: RequestInit = {
      method,
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    };

    if (body !== undefined) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_URL}${endpoint}`, options);
    if (!response.ok) {
      let errorPayload: any = undefined;
      try {
        errorPayload = await response.json();
      } catch {
        // no-op: keep generic error
      }
      const err: any = new Error(errorPayload?.error || `API Error: ${response.statusText}`);
      err.status = response.status;
      throw err;
    }

    return await response.json();
  } catch (error: any) {
    if (error.name === "AbortError") {
      if (timedOut) {
        throw new Error("Server took too long to respond");
      }
      throw error;
    }
    console.error(`Failed to request ${endpoint}:`, error);
    throw error;
  } finally {
    clearTimeout(timeoutId);
    if (signal) {
      signal.removeEventListener("abort", abortByParent);
    }
  }
};

export const getTweetPage = async (
  q: TweetPageQuery,
  signal?: AbortSignal
): Promise<TweetPageResponse> => {
  const params = new URLSearchParams();
  if (q.limit) params.set("limit", String(q.limit));
  if (q.cursor) params.set("cursor", q.cursor);
  if (q.assignedTo) params.set("assignedTo", q.assignedTo);
  if (q.finalLabel) params.set("finalLabel", q.finalLabel);
  if (q.conflictOnly) params.set("conflictOnly", "true");

  const query = params.toString();
  const data = await apiRequest(`/tweets${query ? `?${query}` : ""}`, "GET", undefined, signal);
  return {
    items: data.items || [],
    nextCursor: data.nextCursor ?? null,
    hasMore: Boolean(data.hasMore),
    total: data.total,
  };
};

// Backward compatibility helper (deprecated for large datasets)
export const getTweets = async (): Promise<Tweet[]> => {
  const page = await getTweetPage({ limit: 100 });
  return page.items;
};

export const patchTweetDelta = async (
  tweetId: string,
  delta: TweetDelta
): Promise<PatchTweetResponse> => {
  return await apiRequest(`/tweets/${tweetId}`, "PATCH", delta);
};

export const patchTweetsBulkDelta = async (
  ops: BulkDeltaOperation[]
): Promise<BulkDeltaResponse> => {
  return await apiRequest("/tweets/delta/bulk", "POST", { ops });
};

const tweetToDelta = (tweet: Tweet): TweetDelta => {
  const set: Record<string, unknown> = {
    text: tweet.text,
    annotations: tweet.annotations,
    annotationFeatures: tweet.annotationFeatures || {},
    annotationTimestamps: tweet.annotationTimestamps || {},
  };

  const unset: string[] = [];
  if (tweet.assignedTo !== undefined) {
    set.assignedTo = tweet.assignedTo;
  } else {
    unset.push("assignedTo");
  }

  if (tweet.finalLabel !== undefined) {
    set.finalLabel = tweet.finalLabel;
  } else {
    unset.push("finalLabel");
  }

  return {
    set,
    unset,
    expectedVersion: tweet.v,
  };
};

// Legacy API wrappers routed through delta endpoints
export const saveTweet = async (tweet: Tweet): Promise<PatchTweetResponse> => {
  return patchTweetDelta(tweet.id, tweetToDelta(tweet));
};

export const updateTweets = async (
  updatedTweetsList: Tweet[]
): Promise<BulkDeltaResponse> => {
  const ops: BulkDeltaOperation[] = updatedTweetsList.map((tweet) => ({
    tweetId: tweet.id,
    ...tweetToDelta(tweet),
  }));
  const response = await patchTweetsBulkDelta(ops);
  if (!response.success) {
    const error: any = new Error("Bulk delta update failed");
    error.results = response.results;
    throw error;
  }
  return response;
};

export const addTweets = async (
  newTweets: Tweet[]
): Promise<{ success: boolean; message?: string; insertedCount?: number }> => {
  return await apiRequest("/tweets/add", "POST", newTweets);
};

export const deleteTweet = async (tweetId: string): Promise<void> => {
  await apiRequest(`/tweet/${tweetId}`, "DELETE");
};

export const deleteAllTweets = async (): Promise<{ success: boolean; deletedCount: number }> => {
  return await apiRequest("/tweets", "DELETE");
};

export const getUsers = async (): Promise<User[]> => {
  const data = await apiRequest("/users");
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
  password: string
): Promise<User | null> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}/users/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      signal: controller.signal,
    });

    if (response.status === 401 || response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }
    return await response.json();
  } catch (error: any) {
    if (error.name === "AbortError") {
      throw new Error("Server took too long to respond");
    }
    console.error("Failed to authenticate user:", error);
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
};

export const registerUser = async (user: User): Promise<User> => {
  try {
    return await apiRequest("/users/register", "POST", user);
  } catch {
    throw new Error("שם המשתמש כבר קיים או שיש בעיית תקשורת");
  }
};

export const changePassword = async (
  username: string,
  currentPassword: string,
  newPassword: string
): Promise<{ success: boolean; message?: string; error?: string }> => {
  try {
    return await apiRequest("/users/change-password", "POST", {
      username,
      currentPassword,
      newPassword,
    });
  } catch {
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
    `tweets_labels_detailed_${new Date().toISOString().slice(0, 10)}.csv`
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
  expectedVersion?: number
): Promise<SaveAnnotationResponse> => {
  return await apiRequest("/tweet/annotate", "POST", {
    tweetId,
    username,
    label,
    features,
    timestamp: Date.now(),
    expectedVersion,
  });
};
