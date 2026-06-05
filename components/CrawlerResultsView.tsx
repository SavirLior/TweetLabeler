import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  BarChart2,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Filter,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { Button } from "./Button";
import {
  CrawlerEvidence,
  CrawlerEvidenceAdminStats,
  CrawlerInfluence,
  CrawlerModelLabel,
  CrawlerRun,
  CrawlerStatus,
  CrawlerUser,
  CrawlerUserRun,
  exportCrawlerEvidenceCsv,
  exportCrawlerUsersCsv,
  getCrawlerKeywords,
  getCrawlerEvidence,
  getCrawlerRuns,
  getCrawlerUserRuns,
  getCrawlerUsers,
  saveCrawlerKeywords,
  setCrawlerEvidenceAdminLabel,
  startCrawlerRun,
} from "../services/dataService";

const ADMIN_LABEL_CHOICES: CrawlerModelLabel[] = [
  "Salafi jihadi",
  "Salafi taklidi",
  "Irrelevant",
];

const applyAdminStatsDelta = (
  stats: CrawlerEvidenceAdminStats | null,
  prev: CrawlerModelLabel | undefined,
  next: CrawlerModelLabel | null,
  modelLabel: string | undefined,
  sign: 1 | -1,
): CrawlerEvidenceAdminStats | null => {
  if (!stats) return stats;
  const labeledDelta = (next ? 1 : 0) - (prev ? 1 : 0);
  const modelCountDelta = modelLabel
    ? (next ? 1 : 0) - (prev ? 1 : 0)
    : 0;
  const matchDelta = modelLabel
    ? (next === modelLabel ? 1 : 0) - (prev === modelLabel ? 1 : 0)
    : 0;
  const labeledByAdmin = stats.labeledByAdmin + sign * labeledDelta;
  const totalWithModelLabel = stats.totalWithModelLabel + sign * modelCountDelta;
  const matches = stats.matches + sign * matchDelta;
  const accuracy = totalWithModelLabel > 0 ? matches / totalWithModelLabel : null;
  return { labeledByAdmin, totalWithModelLabel, matches, accuracy };
};

const USER_PAGE_SIZE = 50;
const EVIDENCE_PAGE_SIZE = 100;

type StatusFilter = CrawlerStatus | "all";
type EvidenceLabelFilter = CrawlerModelLabel | "all";
type CrawlerKeywordMode = "default" | "custom";

const statusLabels: Record<StatusFilter, string> = {
  all: "כל הסטטוסים",
  salafi_jihadi: "Salafi jihadi",
  salafi_taklidi: "Salafi taklidi",
  not_salafi_jihadi: "Not salafi jihadi",
  insufficient_data: "Insufficient data",
};

const statusClasses: Record<CrawlerStatus, string> = {
  salafi_jihadi: "bg-red-100 text-red-800 border-red-200",
  salafi_taklidi: "bg-blue-100 text-blue-800 border-blue-200",
  not_salafi_jihadi: "bg-gray-100 text-gray-700 border-gray-200",
  insufficient_data: "bg-yellow-100 text-yellow-800 border-yellow-200",
};

const phaseLabels: Record<string, string> = {
  keyword_trigger: "Trigger",
  profile_deep_dive: "Profile",
};

const evidenceLabelLabels: Record<EvidenceLabelFilter, string> = {
  all: "כל הסיווגים",
  "Salafi jihadi": "Salafi jihadi",
  "Salafi taklidi": "Salafi taklidi",
  Irrelevant: "Irrelevant",
};

const evidenceCountLabels: Record<EvidenceLabelFilter, string> = {
  all: "הכל",
  "Salafi jihadi": "גיהאדי",
  "Salafi taklidi": "תקלידי",
  Irrelevant: "לא רלוונטי",
};

const evidenceLabelOrder: EvidenceLabelFilter[] = [
  "all",
  "Salafi jihadi",
  "Salafi taklidi",
  "Irrelevant",
];

const userStatusOrder: CrawlerStatus[] = [
  "salafi_taklidi",
  "salafi_jihadi",
  "not_salafi_jihadi",
  "insufficient_data",
];

const formatNumber = (value?: number, digits = 3) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
};

const formatCompactNumber = (value?: number | null) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
};

const formatPercent = (value?: number) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(2)}%`;
};

const formatDate = (value?: string) => {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("he-IL", {
    dateStyle: "medium",
    timeStyle: "short",
  });
};

const getEvidenceDate = (evidence: CrawlerEvidence) =>
  evidence.source?.created_at || evidence.collected_at || "";

const getProbabilityEntries = (evidence: CrawlerEvidence) =>
  Object.entries(evidence.probabilities || {}).sort((a, b) => b[1] - a[1]);

const getUserPositiveRatio = (user: CrawlerUser) =>
  user.latest_score?.positive_ratio;

const getUserTaklidiRatio = (user: CrawlerUser) =>
  user.latest_score?.taklidi_ratio;

const getTwitterProfileUrl = (username: string) =>
  `https://x.com/${username.replace(/^@+/, "")}`;

const getInfluenceLocation = (influence?: CrawlerInfluence) =>
  influence?.location?.trim() || "-";

const parseKeywordInput = (value: string) => {
  const seen = new Set<string>();
  return value
    .replace(/,/g, "\n")
    .split(/\r?\n/)
    .map((keyword) => keyword.trim())
    .filter((keyword) => {
      if (!keyword || keyword.startsWith("#")) return false;
      const key = keyword.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};

const getApiErrorText = (error: unknown) => {
  const apiError = error as { status?: number; responseBody?: unknown; message?: string };
  const responseBody = apiError.responseBody;
  let serverMessage = "";
  if (responseBody && typeof responseBody === "object" && "error" in responseBody) {
    serverMessage = String((responseBody as { error?: unknown }).error || "");
  } else if (typeof responseBody === "string") {
    serverMessage = responseBody;
  }

  return [
    apiError.status ? `API ${apiError.status}` : "",
    serverMessage || apiError.message || "Unknown error",
  ]
    .filter(Boolean)
    .join(": ");
};

const hasInfluenceData = (influence?: CrawlerInfluence) =>
  Boolean(
    influence &&
      [
        influence.influence_score,
        influence.followers_count,
        influence.views_count,
        influence.likes_count,
        influence.replies_count,
        influence.shares_count,
        influence.engagement_count,
      ].some((value) => typeof value === "number" && !Number.isNaN(value)),
  );

const logScore = (value?: number | null, fullScoreAt = 1_000_000) => {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) return 0;
  return Math.min(100, (Math.log10(value + 1) / Math.log10(fullScoreAt + 1)) * 100);
};

const calculateInfluenceScore = (influence?: CrawlerInfluence) => {
  if (!hasInfluenceData(influence)) return undefined;
  if (
    typeof influence?.influence_score === "number" &&
    !Number.isNaN(influence.influence_score)
  ) {
    return influence.influence_score;
  }

  const followersScore = logScore(influence?.followers_count, 1_000_000);
  const viewsScore = logScore(influence?.views_count, 1_000_000);
  const engagementScore = logScore(influence?.engagement_count, 100_000);
  const verifiedBonus = influence?.verified ? 5 : 0;
  return Math.round(
    Math.min(
      100,
      followersScore * 0.35 +
        viewsScore * 0.35 +
        engagementScore * 0.25 +
        verifiedBonus,
    ),
  );
};

const getInfluenceTooltip = (influence?: CrawlerInfluence) => {
  const score = calculateInfluenceScore(influence);
  return [
    `Influence score: ${typeof score === "number" ? `${score}/100` : "-"}`,
    `Location: ${getInfluenceLocation(influence)}`,
    `Followers: ${formatCompactNumber(influence?.followers_count)}`,
    `Views: ${formatCompactNumber(influence?.views_count)}`,
    `Likes: ${formatCompactNumber(influence?.likes_count)}`,
    `Replies: ${formatCompactNumber(influence?.replies_count)}`,
    `Shares: ${formatCompactNumber(influence?.shares_count)}`,
    `Engagement: ${formatCompactNumber(influence?.engagement_count)}`,
    "Formula: 35% followers, 35% views, 25% engagement, +5 verified bonus.",
  ].join("\n");
};

const getInfluenceScoreClasses = (score?: number) => {
  if (typeof score !== "number") return "border-gray-200 bg-gray-50 text-gray-500";
  if (score >= 75) return "border-red-200 bg-red-50 text-red-800";
  if (score >= 50) return "border-amber-200 bg-amber-50 text-amber-800";
  if (score >= 25) return "border-blue-200 bg-blue-50 text-blue-800";
  return "border-gray-200 bg-gray-50 text-gray-700";
};

const InfluenceScoreBadge: React.FC<{ influence?: CrawlerInfluence }> = ({ influence }) => {
  const score = calculateInfluenceScore(influence);
  return (
    <span
      title={getInfluenceTooltip(influence)}
      className={`inline-flex min-w-[68px] justify-center rounded-full border px-2.5 py-1 text-xs font-bold ${getInfluenceScoreClasses(
        score,
      )}`}
    >
      {typeof score === "number" ? `${score}/100` : "-"}
    </span>
  );
};

const CrawlerStatusBadge: React.FC<{ status?: CrawlerStatus }> = ({ status }) => {
  if (!status) return <span className="text-gray-400">-</span>;
  return (
    <span
      className={`inline-flex items-center px-2 py-1 text-xs font-semibold rounded-full border ${statusClasses[status]}`}
    >
      {statusLabels[status]}
    </span>
  );
};

type EvidenceItemProps = {
  evidence: CrawlerEvidence;
  onSetAdminLabel: (
    evidence: CrawlerEvidence,
    next: CrawlerModelLabel | null,
  ) => Promise<void>;
};

const EvidenceItem: React.FC<EvidenceItemProps> = ({ evidence, onSetAdminLabel }) => {
  const probabilities = getProbabilityEntries(evidence);
  const [pendingLabel, setPendingLabel] = useState<CrawlerModelLabel | null>(null);
  const isPending = pendingLabel !== null;
  const adminLabel = evidence.admin_label;
  const modelLabel = evidence.model_label;
  const matches =
    adminLabel && modelLabel
      ? adminLabel === modelLabel
      : null;
  const tweetShares =
    typeof evidence.source?.retweet_count === "number" ||
    typeof evidence.source?.quote_count === "number"
      ? (evidence.source?.retweet_count || 0) + (evidence.source?.quote_count || 0)
      : undefined;
  const tweetMetrics = [
    ["Views", evidence.source?.view_count],
    ["Likes", evidence.source?.like_count],
    ["Replies", evidence.source?.reply_count],
    ["Shares", tweetShares],
    ["Bookmarks", evidence.source?.bookmark_count],
  ].filter(([, value]) => typeof value === "number");

  const handleClick = async (choice: CrawlerModelLabel) => {
    if (isPending) return;
    const next: CrawlerModelLabel | null = adminLabel === choice ? null : choice;
    setPendingLabel(choice);
    try {
      await onSetAdminLabel(evidence, next);
    } finally {
      setPendingLabel(null);
    }
  };

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-3">
        <div className="space-y-1">
          <div className="text-xs text-gray-500">{formatDate(getEvidenceDate(evidence))}</div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`px-2 py-1 rounded-full text-xs font-semibold border ${
                evidence.flagged
                  ? "bg-red-100 text-red-800 border-red-200"
                  : "bg-gray-100 text-gray-700 border-gray-200"
              }`}
            >
              {evidence.model_label || "-"}
            </span>
            <span className="text-xs text-gray-500">
              confidence {formatNumber(evidence.confidence, 4)}
            </span>
            <span className="text-xs text-gray-500">
              {phaseLabels[evidence.phase] || evidence.phase}
            </span>
            <span className="text-xs text-gray-400">
              {evidence.run_id || "-"}
            </span>
          </div>
        </div>
        {evidence.tweet_url && (
          <a
            href={evidence.tweet_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
          >
            <ExternalLink className="w-4 h-4" />
            פתח ציוץ
          </a>
        )}
      </div>

      <p className="text-sm leading-6 text-gray-900 whitespace-pre-wrap" dir="auto">
        {evidence.text}
      </p>

      {tweetMetrics.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-600">
          {tweetMetrics.map(([label, value]) => (
            <span
              key={label}
              className="rounded-full border border-gray-200 bg-gray-50 px-2 py-1"
            >
              {label}: {formatCompactNumber(value as number)}
            </span>
          ))}
        </div>
      )}

      {probabilities.length > 0 && (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2">
          {probabilities.map(([label, value]) => (
            <div key={label} className="bg-gray-50 border border-gray-100 rounded-md p-2">
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>{label}</span>
                <span>{formatPercent(value)}</span>
              </div>
              <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-600"
                  style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 pt-3 border-t border-gray-100 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-600">סיווג אדמין:</span>
        {ADMIN_LABEL_CHOICES.map((choice) => {
          const isActive = adminLabel === choice;
          const isThisPending = pendingLabel === choice;
          return (
            <button
              key={choice}
              type="button"
              onClick={() => handleClick(choice)}
              disabled={isPending}
              className={`px-2.5 py-1 rounded-full border text-xs font-semibold transition-colors ${
                isActive
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
              } ${isPending && !isThisPending ? "opacity-50" : ""}`}
            >
              {choice}
            </button>
          );
        })}
        {matches !== null && (
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${
              matches
                ? "bg-green-50 text-green-700 border-green-200"
                : "bg-red-50 text-red-700 border-red-200"
            }`}
            title={
              matches
                ? "תיוג האדמין תואם את תחזית המודל"
                : "תיוג האדמין שונה מתחזית המודל"
            }
          >
            {matches ? "✓ תואם מודל" : "✗ שונה ממודל"}
          </span>
        )}
        {adminLabel && (
          <span className="text-xs text-gray-400">
            {evidence.admin_label_by ? `by @${evidence.admin_label_by}` : ""}
            {evidence.admin_label_at ? ` • ${formatDate(evidence.admin_label_at)}` : ""}
          </span>
        )}
      </div>
    </div>
  );
};

export const CrawlerResultsView: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [runFilter, setRunFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [crawlerRuns, setCrawlerRuns] = useState<CrawlerRun[]>([]);
  const [users, setUsers] = useState<CrawlerUser[]>([]);
  const [usersCursor, setUsersCursor] = useState<string | null>(null);
  const [usersTotal, setUsersTotal] = useState(0);
  const [userStatusCounts, setUserStatusCounts] =
    useState<Partial<Record<CrawlerStatus, number>>>({});
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState("");

  const [selectedUser, setSelectedUser] = useState<CrawlerUser | null>(null);
  const [userRuns, setUserRuns] = useState<CrawlerUserRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("all");
  const [runsLoading, setRunsLoading] = useState(false);
  const [evidence, setEvidence] = useState<CrawlerEvidence[]>([]);
  const [evidenceCursor, setEvidenceCursor] = useState<string | null>(null);
  const [evidenceTotal, setEvidenceTotal] = useState(0);
  const [evidenceLabelCounts, setEvidenceLabelCounts] = useState<Record<string, number>>({});
  const [evidenceAdminStats, setEvidenceAdminStats] =
    useState<CrawlerEvidenceAdminStats | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [labelFilter, setLabelFilter] = useState<EvidenceLabelFilter>("all");
  const [showStats, setShowStats] = useState(true);
  const [exporting, setExporting] = useState<"users" | "evidence" | null>(null);
  const [defaultKeywords, setDefaultKeywords] = useState<string[]>([]);
  const [editableDefaultKeywords, setEditableDefaultKeywords] = useState<string[]>([]);
  const [newDefaultKeyword, setNewDefaultKeyword] = useState("");
  const [keywordMode, setKeywordMode] = useState<CrawlerKeywordMode>("default");
  const [customKeywords, setCustomKeywords] = useState<string[]>([]);
  const [newCustomKeyword, setNewCustomKeyword] = useState("");
  const [keywordsLoading, setKeywordsLoading] = useState(false);
  const [keywordsError, setKeywordsError] = useState("");
  const [keywordsSaving, setKeywordsSaving] = useState(false);
  const [crawlerStartLoading, setCrawlerStartLoading] = useState(false);
  const [crawlerStartMessage, setCrawlerStartMessage] = useState("");
  const [crawlerStartError, setCrawlerStartError] = useState("");

  const formatRunOptionLabel = (run: CrawlerRun) => {
    const started = formatDate(run.started_at);
    const count = run.counts?.deep_dived_users;
    return `${started} - ${run.run_id}${typeof count === "number" ? ` (${count})` : ""}`;
  };

  const loadCrawlerRuns = async (signal?: AbortSignal) => {
    try {
      const response = await getCrawlerRuns(signal);
      if (signal?.aborted) return;
      setCrawlerRuns(response.items);
    } catch {
      if (signal?.aborted) return;
      setCrawlerRuns([]);
    }
  };

  const loadCrawlerKeywords = async (signal?: AbortSignal) => {
    setKeywordsLoading(true);
    setKeywordsError("");
    try {
      const response = await getCrawlerKeywords(signal);
      if (signal?.aborted) return;
      setDefaultKeywords(response.items);
      setEditableDefaultKeywords(response.items);
    } catch (error) {
      if (signal?.aborted) return;
      setDefaultKeywords([]);
      setEditableDefaultKeywords([]);
      setKeywordsError(
        `Could not load keywords from keywords.txt. ${getApiErrorText(error)}`,
      );
    } finally {
      if (signal?.aborted) return;
      setKeywordsLoading(false);
    }
  };

  const loadUsers = async (
    mode: "replace" | "append" = "replace",
    signal?: AbortSignal,
  ) => {
    setUsersLoading(true);
    setUsersError("");
    try {
      const response = await getCrawlerUsers({
        status: statusFilter,
        runId: runFilter,
        search: search.trim(),
        limit: USER_PAGE_SIZE,
        cursor: mode === "append" ? usersCursor || undefined : undefined,
      }, signal);
      if (signal?.aborted) return;
      setUsers((prev) =>
        mode === "append" ? [...prev, ...response.items] : response.items,
      );
      setUsersCursor(response.nextCursor);
      setUsersTotal(response.total);
      setUserStatusCounts(response.statusCounts || {});
      if (mode === "replace") {
        setSelectedUser((current) => {
          if (!current) return response.items[0] || null;
          return (
            response.items.find((user) => user.username_key === current.username_key) ||
            response.items[0] ||
            null
          );
        });
      }
    } catch (error) {
      if (signal?.aborted) return;
      setUsersError(error instanceof Error ? error.message : "שגיאה בטעינת משתמשים");
    } finally {
      if (signal?.aborted) return;
      setUsersLoading(false);
    }
  };

  const loadEvidence = async (
    mode: "replace" | "append" = "replace",
    signal?: AbortSignal,
  ) => {
    if (!selectedUser) return;

    setEvidenceLoading(true);
    setEvidenceError("");
    try {
      const response = await getCrawlerEvidence({
        usernameKey: selectedUser.username_key,
        runId: selectedRunId,
        label: labelFilter,
        limit: EVIDENCE_PAGE_SIZE,
        cursor: mode === "append" ? evidenceCursor || undefined : undefined,
      }, signal);
      if (signal?.aborted) return;
      setEvidence((prev) =>
        mode === "append" ? [...prev, ...response.items] : response.items,
      );
      setEvidenceCursor(response.nextCursor);
      setEvidenceTotal(response.total);
      setEvidenceLabelCounts(response.labelCounts || {});
      setEvidenceAdminStats(response.adminStats || null);
    } catch (error) {
      if (signal?.aborted) return;
      setEvidenceError(error instanceof Error ? error.message : "שגיאה בטעינת evidence");
    } finally {
      if (signal?.aborted) return;
      setEvidenceLoading(false);
    }
  };

  const loadUserRuns = async (user: CrawlerUser, signal?: AbortSignal) => {
    setRunsLoading(true);
    try {
      const response = await getCrawlerUserRuns(user.username_key, signal);
      if (signal?.aborted) return;
      setUserRuns(response.items);
      setSelectedRunId((current) => {
        if (
          runFilter !== "all" &&
          response.items.some((run) => run.run_id === runFilter)
        ) {
          return runFilter;
        }
        if (
          current !== "all" &&
          response.items.some((run) => run.run_id === current)
        ) {
          return current;
        }
        if (
          user.latest_run_id &&
          response.items.some((run) => run.run_id === user.latest_run_id)
        ) {
          return user.latest_run_id;
        }
        return response.items[0]?.run_id || user.latest_run_id || "all";
      });
    } catch {
      if (signal?.aborted) return;
      setUserRuns([]);
      setSelectedRunId(user.latest_run_id || "all");
    } finally {
      if (signal?.aborted) return;
      setRunsLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadCrawlerRuns(controller.signal);
    loadCrawlerKeywords(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      loadUsers("replace", controller.signal);
    }, 250);
    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [statusFilter, runFilter, search]);

  useEffect(() => {
    if (
      selectedUser &&
      selectedRunId !== "all" &&
      selectedUser.latest_run_id &&
      selectedRunId !== selectedUser.latest_run_id &&
      !userRuns.some((run) => run.run_id === selectedRunId)
    ) {
      return;
    }
    const controller = new AbortController();
    setEvidence([]);
    setEvidenceCursor(null);
    setEvidenceTotal(0);
    setEvidenceLabelCounts({});
    setEvidenceAdminStats(null);
    loadEvidence("replace", controller.signal);
    return () => controller.abort();
  }, [selectedUser?.username_key, selectedRunId, labelFilter, userRuns]);

  useEffect(() => {
    if (!selectedUser) {
      setUserRuns([]);
      setSelectedRunId("all");
      setLabelFilter("all");
      return;
    }
    const controller = new AbortController();
    setUserRuns([]);
    setSelectedRunId(runFilter !== "all" ? runFilter : selectedUser.latest_run_id || "all");
    setLabelFilter("all");
    loadUserRuns(selectedUser, controller.signal);
    return () => controller.abort();
  }, [selectedUser?.username_key, runFilter]);

  const selectedScore = selectedUser?.latest_score || {};
  const selectedThresholds = selectedUser?.latest_thresholds || {};
  const selectedRun = userRuns.find((run) => run.run_id === selectedRunId);
  const activeScore = selectedRun?.score || selectedScore;
  const activeThresholds = selectedRun?.thresholds || selectedThresholds;
  const activeInfluence: CrawlerInfluence =
    selectedRun?.influence || selectedUser?.latest_influence || {};
  const activeTaklidiLead =
    typeof activeScore.taklidi_ratio === "number" &&
    typeof activeScore.positive_ratio === "number"
      ? activeScore.taklidi_ratio - activeScore.positive_ratio
      : undefined;
  const allEvidenceLabelCount = Object.values(evidenceLabelCounts).reduce(
    (sum, count) => sum + count,
    0,
  );
  const activeEvidenceCount =
    labelFilter === "all"
      ? evidenceTotal
      : evidenceLabelCounts[labelFilter] ?? evidenceTotal;

  const selectedKeywords = useMemo(
    () => selectedUser?.discovered_by_keywords || [],
    [selectedUser],
  );
  const statusSummaryTotal = userStatusOrder.reduce(
    (sum, status) => sum + (userStatusCounts[status] || 0),
    0,
  );
  const activeCrawlerKeywords =
    keywordMode === "default" ? editableDefaultKeywords : customKeywords;

  const updateKeyword = (
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    index: number,
    value: string,
  ) => {
    setter((current) =>
      current.map((keyword, keywordIndex) => (keywordIndex === index ? value : keyword)),
    );
  };

  const moveKeyword = (
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    index: number,
    direction: -1 | 1,
  ) => {
    setter((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  };

  const removeKeyword = (
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    index: number,
  ) => {
    setter((current) =>
      current.filter((_keyword, keywordIndex) => keywordIndex !== index),
    );
  };

  const addKeyword = (
    listSetter: React.Dispatch<React.SetStateAction<string[]>>,
    inputValue: string,
    inputSetter: React.Dispatch<React.SetStateAction<string>>,
  ) => {
    const [keyword] = parseKeywordInput(inputValue);
    if (!keyword) return;
    listSetter((current) => {
      if (current.some((existing) => existing.toLocaleLowerCase() === keyword.toLocaleLowerCase())) {
        return current;
      }
      return [...current, keyword];
    });
    inputSetter("");
  };

  const shuffleKeywords = (setter: React.Dispatch<React.SetStateAction<string[]>>) => {
    setter((current) => {
      const next = [...current];
      for (let index = next.length - 1; index > 0; index -= 1) {
        const swapIndex = Math.floor(Math.random() * (index + 1));
        [next[index], next[swapIndex]] = [next[swapIndex], next[index]];
      }
      return next;
    });
  };

  const resetDefaultKeywords = () => {
    setEditableDefaultKeywords(defaultKeywords);
    setNewDefaultKeyword("");
  };

  const handleUsersExport = async () => {
    setExporting("users");
    try {
      await exportCrawlerUsersCsv({
        status: statusFilter,
        runId: runFilter,
        search: search.trim(),
      });
    } finally {
      setExporting(null);
    }
  };

  const handleSaveDefaultKeywords = async () => {
    const keywords = parseKeywordInput(editableDefaultKeywords.join("\n"));
    if (keywords.length === 0) {
      setKeywordsError("At least one keyword is required.");
      return;
    }

    setKeywordsSaving(true);
    setKeywordsError("");
    try {
      const response = await saveCrawlerKeywords(keywords);
      setDefaultKeywords(response.items);
      setEditableDefaultKeywords(response.items);
      setCrawlerStartMessage("Default keyword file saved.");
      setCrawlerStartError("");
    } catch (error) {
      const responseBody = (error as { responseBody?: { error?: string } }).responseBody;
      setKeywordsError(
        responseBody?.error ||
          (error instanceof Error ? error.message : "Failed to save keywords."),
      );
    } finally {
      setKeywordsSaving(false);
    }
  };

  const handleStartCrawlerRun = async () => {
    const keywords = parseKeywordInput(activeCrawlerKeywords.join("\n"));
    if (keywordMode === "custom" && keywords.length === 0) {
      setCrawlerStartError("Please enter at least one keyword.");
      setCrawlerStartMessage("");
      return;
    }
    if (keywordMode === "default" && editableDefaultKeywords.length === 0 && keywordsError) {
      setCrawlerStartError("Default keywords are not loaded.");
      setCrawlerStartMessage("");
      return;
    }

    setCrawlerStartLoading(true);
    setCrawlerStartError("");
    setCrawlerStartMessage("");
    try {
      const response = await startCrawlerRun({
        useDefaultKeywords: keywordMode === "default" && keywords.length === 0,
        keywords: keywords.length > 0 ? keywords : undefined,
      });
      setCrawlerStartMessage(
        `Crawler started with ${response.keywordCount ?? keywords.length} ${
          response.keywordCount === 1 ? "keyword" : "keywords"
        }. Refresh the runs list in a few moments to follow progress.`,
      );
      await loadCrawlerRuns();
    } catch (error) {
      const responseBody = (error as { responseBody?: { error?: string } }).responseBody;
      setCrawlerStartError(
        responseBody?.error ||
          (error instanceof Error ? error.message : "Failed to start crawler."),
      );
    } finally {
      setCrawlerStartLoading(false);
    }
  };

  const handleSetAdminLabel = async (
    target: CrawlerEvidence,
    next: CrawlerModelLabel | null,
  ) => {
    if (!target._id) return;
    const evidenceId = target._id;
    const prev = target.admin_label;
    if (prev === (next ?? undefined)) return;
    const modelLabel = target.model_label;

    setEvidence((current) =>
      current.map((item) =>
        item._id === evidenceId
          ? {
              ...item,
              admin_label: next ?? undefined,
              admin_label_by: undefined,
              admin_label_at: undefined,
            }
          : item,
      ),
    );
    setEvidenceAdminStats((stats) =>
      applyAdminStatsDelta(stats, prev, next, modelLabel, 1),
    );

    try {
      const response = await setCrawlerEvidenceAdminLabel(evidenceId, next);
      if (response.item) {
        const updated = response.item;
        setEvidence((current) =>
          current.map((item) => (item._id === evidenceId ? { ...item, ...updated } : item)),
        );
      }
      if (response.adminStats) {
        setEvidenceAdminStats(response.adminStats);
      }
    } catch (error) {
      setEvidence((current) =>
        current.map((item) =>
          item._id === evidenceId
            ? {
                ...item,
                admin_label: prev,
                admin_label_by: target.admin_label_by,
                admin_label_at: target.admin_label_at,
              }
            : item,
        ),
      );
      setEvidenceAdminStats((stats) =>
        applyAdminStatsDelta(stats, prev, next, modelLabel, -1),
      );
      setEvidenceError(
        error instanceof Error ? error.message : "שגיאה בעדכון תיוג אדמין",
      );
    }
  };

  const handleEvidenceExport = async () => {
    if (!selectedUser) return;
    setExporting("evidence");
    try {
      await exportCrawlerEvidenceCsv(selectedUser.username_key, {
        runId: selectedRunId,
        label: labelFilter,
      });
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900">תוצאות זחלן</h2>
            <p className="text-sm text-gray-500 mt-1">
              משתמשים שנבדקו ב-deep dive והציוצים שהמודל ראה בפועל
            </p>
          </div>
          <div className="flex flex-col sm:flex-row gap-2">
            <Button
              onClick={() => loadUsers("replace")}
              variant="secondary"
              disabled={usersLoading}
              className="flex items-center justify-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${usersLoading ? "animate-spin" : ""}`} />
              רענן
            </Button>
            <Button
              onClick={handleUsersExport}
              variant="secondary"
              disabled={exporting === "users"}
              className="flex items-center justify-center gap-2"
            >
              <Download className="w-4 h-4" />
              Export users
            </Button>
          </div>
        </div>

        <div className="mt-4 border border-gray-200 rounded-lg bg-gray-50 p-3 space-y-3">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
            <div className="inline-flex w-fit rounded-lg border border-gray-200 bg-white p-1">
              <button
                type="button"
                onClick={() => setKeywordMode("default")}
                className={`px-3 py-1.5 rounded-md text-sm font-semibold ${
                  keywordMode === "default"
                    ? "bg-blue-600 text-white"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                Default file ({editableDefaultKeywords.length})
              </button>
              <button
                type="button"
                onClick={() => setKeywordMode("custom")}
                className={`px-3 py-1.5 rounded-md text-sm font-semibold ${
                  keywordMode === "custom"
                    ? "bg-blue-600 text-white"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                Custom ({customKeywords.length})
              </button>
            </div>

            <div className="flex flex-wrap gap-2">
              {keywordMode === "default" && (
                <>
                  <Button
                    onClick={handleSaveDefaultKeywords}
                    variant="secondary"
                    disabled={keywordsSaving || editableDefaultKeywords.length === 0}
                  >
                    {keywordsSaving ? "Saving..." : "Save file"}
                  </Button>
                  <Button
                    onClick={() => loadCrawlerKeywords()}
                    variant="secondary"
                    disabled={keywordsLoading}
                  >
                    {keywordsLoading ? "Loading..." : "Reload file"}
                  </Button>
                  <Button
                    onClick={resetDefaultKeywords}
                    variant="secondary"
                    disabled={keywordsLoading}
                  >
                    Reset
                  </Button>
                  <Button
                    onClick={() => shuffleKeywords(setEditableDefaultKeywords)}
                    variant="secondary"
                    disabled={editableDefaultKeywords.length < 2}
                  >
                    Shuffle
                  </Button>
                </>
              )}
              {keywordMode === "custom" && (
                <Button
                  onClick={() => shuffleKeywords(setCustomKeywords)}
                  variant="secondary"
                  disabled={customKeywords.length < 2}
                >
                  Shuffle
                </Button>
              )}
              <Button
                onClick={handleStartCrawlerRun}
                variant="primary"
                disabled={crawlerStartLoading}
                className="flex items-center justify-center gap-2 whitespace-nowrap"
              >
                <Play className="w-4 h-4" />
                {crawlerStartLoading ? "Starting..." : "Start crawl"}
              </Button>
            </div>
          </div>

          {keywordMode === "default" ? (
            <div className="space-y-2">
              <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 space-y-1">
                {editableDefaultKeywords.map((keyword, index) => (
                  <div key={`${keyword}-${index}`} className="flex items-center gap-2">
                    <span className="w-8 text-left text-xs text-gray-400" dir="ltr">
                      {index + 1}
                    </span>
                    <input
                      value={keyword}
                      onChange={(event) =>
                        updateKeyword(setEditableDefaultKeywords, index, event.target.value)
                      }
                      className="min-w-0 flex-1 rounded-md border border-gray-200 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      dir="auto"
                    />
                    <button
                      type="button"
                      onClick={() => moveKeyword(setEditableDefaultKeywords, index, -1)}
                      disabled={index === 0}
                      className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                      title="Move up"
                    >
                      <ArrowUp className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => moveKeyword(setEditableDefaultKeywords, index, 1)}
                      disabled={index === editableDefaultKeywords.length - 1}
                      className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                      title="Move down"
                    >
                      <ArrowDown className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeKeyword(setEditableDefaultKeywords, index)}
                      className="rounded-md border border-red-200 bg-white p-1.5 text-red-600 hover:bg-red-50"
                      title="Remove"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
                {!keywordsLoading && editableDefaultKeywords.length === 0 && (
                  <div className="py-6 text-center text-sm text-gray-500">
                    No keywords loaded
                  </div>
                )}
                {keywordsLoading && (
                  <div className="py-6 text-center text-sm text-gray-500">Loading...</div>
                )}
              </div>

              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  value={newDefaultKeyword}
                  onChange={(event) => setNewDefaultKeyword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addKeyword(
                        setEditableDefaultKeywords,
                        newDefaultKeyword,
                        setNewDefaultKeyword,
                      );
                    }
                  }}
                  placeholder="Add keyword or phrase"
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  dir="auto"
                />
                <Button
                  onClick={() =>
                    addKeyword(
                      setEditableDefaultKeywords,
                      newDefaultKeyword,
                      setNewDefaultKeyword,
                    )
                  }
                  variant="secondary"
                  className="flex items-center justify-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Add
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 space-y-1">
                {customKeywords.map((keyword, index) => (
                  <div key={`${keyword}-${index}`} className="flex items-center gap-2">
                    <span className="w-8 text-left text-xs text-gray-400" dir="ltr">
                      {index + 1}
                    </span>
                    <input
                      value={keyword}
                      readOnly
                      className="min-w-0 flex-1 rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-sm text-gray-700"
                      dir="auto"
                    />
                    <button
                      type="button"
                      onClick={() => moveKeyword(setCustomKeywords, index, -1)}
                      disabled={index === 0}
                      className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                      title="Move up"
                    >
                      <ArrowUp className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => moveKeyword(setCustomKeywords, index, 1)}
                      disabled={index === customKeywords.length - 1}
                      className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                      title="Move down"
                    >
                      <ArrowDown className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeKeyword(setCustomKeywords, index)}
                      className="rounded-md border border-red-200 bg-white p-1.5 text-red-600 hover:bg-red-50"
                      title="Remove"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
                {customKeywords.length === 0 && (
                  <div className="py-6 text-center text-sm text-gray-500">
                    Add custom keywords or phrases below
                  </div>
                )}
              </div>

              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  value={newCustomKeyword}
                  onChange={(event) => setNewCustomKeyword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addKeyword(setCustomKeywords, newCustomKeyword, setNewCustomKeyword);
                    }
                  }}
                  placeholder="Add custom keyword or phrase"
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  dir="auto"
                />
                <Button
                  onClick={() => addKeyword(setCustomKeywords, newCustomKeyword, setNewCustomKeyword)}
                  variant="secondary"
                  className="flex items-center justify-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Add
                </Button>
              </div>
            </div>
          )}

          {(keywordsError || crawlerStartMessage || crawlerStartError) && (
            <div
              className={`text-sm ${
                keywordsError || crawlerStartError ? "text-red-700" : "text-green-700"
              }`}
            >
              {keywordsError || crawlerStartError || crawlerStartMessage}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_220px_280px] gap-3 mt-4">
          <label className="relative">
            <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="חיפוש username"
              className="w-full pr-10 pl-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <label className="relative">
            <Filter className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
              className="w-full pr-10 pl-3 py-2 border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="relative">
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <select
              value={runFilter}
              onChange={(event) => setRunFilter(event.target.value)}
              className="w-full pr-10 pl-3 py-2 border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All crawls</option>
              {crawlerRuns.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {formatRunOptionLabel(run)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="space-y-6">
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
            <div className="text-sm font-semibold text-gray-800">
              משתמשים ({users.length}/{usersTotal})
            </div>
            {usersError && <div className="text-sm text-red-600">{usersError}</div>}
          </div>

          <div className="px-4 py-4 border-b border-gray-100 bg-gray-50">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {userStatusOrder.map((status) => {
                const count = userStatusCounts[status] || 0;
                const ratio = statusSummaryTotal > 0 ? count / statusSummaryTotal : undefined;
                return (
                  <button
                    key={status}
                    type="button"
                    onClick={() => setStatusFilter(status)}
                    className={`text-right rounded-md border p-3 transition-colors ${
                      statusFilter === status
                        ? "border-blue-500 bg-white ring-2 ring-blue-100"
                        : "border-gray-200 bg-white hover:bg-blue-50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <CrawlerStatusBadge status={status} />
                      <span className="text-lg font-bold text-gray-900">{count}</span>
                    </div>
                    <div className="mt-2 text-xs text-gray-500">
                      {formatPercent(ratio)} of filtered users
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Username
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Status
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Influence
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Jihadi
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Jihadi %
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Taklidi
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Taklidi %
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Seen
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {users.map((user) => {
                  const isSelected = selectedUser?.username_key === user.username_key;
                  const influence = user.latest_influence || {};
                  return (
                    <tr
                      key={user.username_key}
                      onClick={() => setSelectedUser(user)}
                      className={`cursor-pointer hover:bg-blue-50 ${
                        isSelected ? "bg-blue-50" : ""
                      }`}
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        <div className="flex items-center gap-2">
                          <span>@{user.username}</span>
                          <a
                            href={getTwitterProfileUrl(user.username)}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(event) => event.stopPropagation()}
                            className="inline-flex items-center text-blue-600 hover:text-blue-800"
                            title="Open X profile"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <CrawlerStatusBadge status={user.current_status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        <InfluenceScoreBadge influence={influence} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700" dir="ltr">
                        {user.latest_score?.positive_count ?? "-"} /{" "}
                        {user.latest_score?.evaluated_count ?? "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {formatPercent(getUserPositiveRatio(user))}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700" dir="ltr">
                        {user.latest_score?.taklidi_count ?? "-"} /{" "}
                        {user.latest_score?.evaluated_count ?? "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {formatPercent(getUserTaklidiRatio(user))}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(user.last_seen_at)}
                      </td>
                    </tr>
                  );
                })}
                {!usersLoading && users.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                      אין תוצאות להצגה
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="px-4 py-3 border-t border-gray-200 flex justify-center">
            {usersCursor ? (
              <Button
                onClick={() => loadUsers("append")}
                variant="secondary"
                disabled={usersLoading}
              >
                טען עוד משתמשים
              </Button>
            ) : (
              <span className="text-xs text-gray-400">אין עוד משתמשים</span>
            )}
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg shadow-sm min-h-[520px]">
          {selectedUser ? (
            <div className="h-full flex flex-col">
              <div className="p-4 border-b border-gray-200 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-bold text-gray-900">
                        @{selectedUser.username}
                      </h3>
                      <a
                        href={getTwitterProfileUrl(selectedUser.username)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center text-blue-600 hover:text-blue-800"
                        title="Open X profile"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                      <CrawlerStatusBadge status={selectedUser.current_status} />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      latest run: {selectedUser.latest_run_id || "-"}
                    </p>
                  </div>
                  <Button
                    onClick={handleEvidenceExport}
                    variant="secondary"
                    disabled={exporting === "evidence"}
                    className="flex items-center justify-center gap-2"
                  >
                    <Download className="w-4 h-4" />
                    Export evidence
                  </Button>
                </div>

                <button
                  onClick={() => setShowStats((value) => !value)}
                  className="w-full flex items-center justify-between text-sm font-semibold text-gray-700 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2"
                >
                  <span className="flex items-center gap-2">
                    <BarChart2 className="w-4 h-4 text-blue-600" />
                    סטטיסטיקות והגדרות ריצה
                  </span>
                  {showStats ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>

                {showStats && (
                  <div className="space-y-3 text-sm">
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                        <div className="text-xs text-gray-500">Evaluated profile</div>
                        <div className="font-semibold text-gray-900">
                          {activeScore.evaluated_count ?? "-"}
                        </div>
                      </div>
                      <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                        <div className="text-xs text-gray-500">Min profile</div>
                        <div className="font-semibold text-gray-900">
                          {activeThresholds.min_profile_evaluated_tweets ?? "-"}
                        </div>
                      </div>
                      <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                        <div className="text-xs text-gray-500">Evidence shown</div>
                        <div className="font-semibold text-gray-900">{evidenceTotal}</div>
                      </div>
                    </div>

                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3 space-y-3">
                      <div className="text-sm font-bold text-gray-900">Influence</div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div>
                          <div className="text-xs text-gray-500">Score</div>
                          <div className="mt-1">
                            <InfluenceScoreBadge influence={activeInfluence} />
                          </div>
                        </div>
                        <div className="md:col-span-2">
                          <div className="text-xs text-gray-500">Location</div>
                          <div
                            className="font-semibold text-gray-900 truncate"
                            title={getInfluenceLocation(activeInfluence)}
                          >
                            {getInfluenceLocation(activeInfluence)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Followers</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.followers_count)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Views</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.views_count)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Likes</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.likes_count)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Replies</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.replies_count)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Shares</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.shares_count)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Engagement</div>
                          <div className="font-semibold text-gray-900">
                            {formatCompactNumber(activeInfluence.engagement_count)}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="bg-red-50 border border-red-100 rounded-md p-3 space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-bold text-red-900">Salafi jihadi</div>
                          <button
                            type="button"
                            onClick={() => setLabelFilter("Salafi jihadi")}
                            className="px-2 py-1 rounded-full border border-red-200 bg-white text-xs font-semibold text-red-700 hover:bg-red-100"
                          >
                            View tweets
                          </button>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <div className="text-xs text-red-700/70">Tweets</div>
                            <div className="font-semibold text-red-950" dir="ltr">
                              {activeScore.positive_count ?? "-"} /{" "}
                              {activeScore.evaluated_count ?? "-"}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-red-700/70">Ratio</div>
                            <div className="font-semibold text-red-950">
                              {formatPercent(activeScore.positive_ratio)}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-red-700/70">Tweet threshold</div>
                            <div className="font-semibold text-red-950">
                              &gt; {activeThresholds.min_positive_tweets ?? "-"}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-red-700/70">Ratio threshold</div>
                            <div className="font-semibold text-red-950">
                              &gt; {formatPercent(activeThresholds.positive_ratio_threshold)}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="bg-blue-50 border border-blue-100 rounded-md p-3 space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-bold text-blue-900">Salafi taklidi</div>
                          <button
                            type="button"
                            onClick={() => setLabelFilter("Salafi taklidi")}
                            className="px-2 py-1 rounded-full border border-blue-200 bg-white text-xs font-semibold text-blue-700 hover:bg-blue-100"
                          >
                            View tweets
                          </button>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <div className="text-xs text-blue-700/70">Tweets</div>
                            <div className="font-semibold text-blue-950" dir="ltr">
                              {activeScore.taklidi_count ?? "-"} /{" "}
                              {activeScore.evaluated_count ?? "-"}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-blue-700/70">Ratio</div>
                            <div className="font-semibold text-blue-950">
                              {formatPercent(activeScore.taklidi_ratio)}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-blue-700/70">Ratio threshold</div>
                            <div className="font-semibold text-blue-950">
                              &gt; {formatPercent(activeThresholds.taklidi_ratio_threshold)}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-blue-700/70">Lead over jihadi</div>
                            <div className="font-semibold text-blue-950">
                              {formatPercent(activeTaklidiLead)} /{" "}
                              {formatPercent(activeThresholds.taklidi_ratio_margin)}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {selectedKeywords.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {selectedKeywords.slice(0, 12).map((keyword) => (
                      <span
                        key={keyword}
                        className="px-2 py-1 rounded-full bg-blue-50 text-blue-700 text-xs border border-blue-100"
                      >
                        {keyword}
                      </span>
                    ))}
                    {selectedKeywords.length > 12 && (
                      <span className="px-2 py-1 rounded-full bg-gray-50 text-gray-500 text-xs border border-gray-100">
                        +{selectedKeywords.length - 12}
                      </span>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="space-y-1">
                    <span className="text-xs font-semibold text-gray-600">
                      הרצה להצגה
                    </span>
                    <select
                      value={selectedRunId}
                      onChange={(event) => setSelectedRunId(event.target.value)}
                      disabled={runsLoading}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="all">כל ההרצות</option>
                      {userRuns.map((run) => (
                        <option key={run.run_id} value={run.run_id}>
                          {run.run_id === selectedUser.latest_run_id
                            ? "הרצה אחרונה"
                            : "הרצה"}{" "}
                          - {formatDate(run.created_at)} - {run.status || "-"}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="space-y-1">
                    <span className="text-xs font-semibold text-gray-600">
                      סיווג ציוץ
                    </span>
                    <select
                      value={labelFilter}
                      onChange={(event) =>
                        setLabelFilter(event.target.value as EvidenceLabelFilter)
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {Object.entries(evidenceLabelLabels).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {evidenceLabelOrder.map((label) => {
                    const count =
                      label === "all"
                        ? allEvidenceLabelCount || evidenceTotal
                        : evidenceLabelCounts[label] || 0;
                    const isActive = labelFilter === label;
                    return (
                      <button
                        key={label}
                        type="button"
                        onClick={() => setLabelFilter(label)}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${
                          isActive
                            ? "border-blue-600 bg-blue-50 text-blue-800"
                            : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        <span>{evidenceCountLabels[label]}</span>
                        <span
                          className={`rounded-full px-2 py-0.5 ${
                            isActive
                              ? "bg-blue-600 text-white"
                              : "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {count}
                        </span>
                      </button>
                    );
                  })}
                  <span className="text-xs text-gray-500">
                    מוצגים עכשיו: {activeEvidenceCount}
                  </span>
                </div>

                {evidenceAdminStats && (
                  <div className="flex flex-wrap items-center gap-3 bg-blue-50 border border-blue-100 rounded-md px-3 py-2 text-xs text-blue-900">
                    <span className="font-semibold">דיוק מודל לפי האדמין:</span>
                    <span className="font-bold">
                      {evidenceAdminStats.accuracy === null
                        ? "-"
                        : `${(evidenceAdminStats.accuracy * 100).toFixed(1)}%`}
                    </span>
                    <span className="text-blue-800/80">
                      ({evidenceAdminStats.matches}/
                      {evidenceAdminStats.totalWithModelLabel} תואמים)
                    </span>
                    <span className="text-blue-800/60">
                      • {evidenceAdminStats.labeledByAdmin} תוייגו ע״י אדמין
                    </span>
                  </div>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50">
                {evidenceError && (
                  <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                    {evidenceError}
                  </div>
                )}
                {evidence.map((item) => (
                  <EvidenceItem
                    key={
                      item._id ||
                      `${item.run_id || "-"}-${item.phase || "-"}-${
                        item.tweet_key || item.tweet_id || item.tweet_url || item.text
                      }`
                    }
                    evidence={item}
                    onSetAdminLabel={handleSetAdminLabel}
                  />
                ))}
                {!evidenceLoading && evidence.length === 0 && (
                  <div className="text-center text-gray-500 py-12">
                    אין evidence להצגה עבור המשתמש הזה
                  </div>
                )}
                {evidenceCursor && (
                  <div className="flex justify-center pt-2">
                    <Button
                      onClick={() => loadEvidence("append")}
                      variant="secondary"
                      disabled={evidenceLoading}
                    >
                      טען עוד evidence
                    </Button>
                  </div>
                )}
                {evidenceLoading && (
                  <div className="text-center text-sm text-gray-500 py-4">טוען...</div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-gray-500 p-8 text-center">
              בחר משתמש מהרשימה כדי לראות evidence וסטטיסטיקות
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
