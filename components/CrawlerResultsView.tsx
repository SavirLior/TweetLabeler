import React, { useEffect, useMemo, useState } from "react";
import {
  BarChart2,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Filter,
  RefreshCw,
  Search,
} from "lucide-react";
import { Button } from "./Button";
import {
  CrawlerEvidence,
  CrawlerModelLabel,
  CrawlerStatus,
  CrawlerUser,
  CrawlerUserRun,
  exportCrawlerEvidenceCsv,
  exportCrawlerUsersCsv,
  getCrawlerEvidence,
  getCrawlerUserRuns,
  getCrawlerUsers,
} from "../services/dataService";

const USER_PAGE_SIZE = 50;
const EVIDENCE_PAGE_SIZE = 100;

type StatusFilter = CrawlerStatus | "all";
type EvidenceLabelFilter = CrawlerModelLabel | "all";

const statusLabels: Record<StatusFilter, string> = {
  all: "כל הסטטוסים",
  salafi_jihadi: "Salafi jihadi",
  not_salafi_jihadi: "Not salafi jihadi",
  insufficient_data: "Insufficient data",
};

const statusClasses: Record<CrawlerStatus, string> = {
  salafi_jihadi: "bg-red-100 text-red-800 border-red-200",
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

const formatNumber = (value?: number, digits = 3) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
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

const EvidenceItem: React.FC<{ evidence: CrawlerEvidence }> = ({ evidence }) => {
  const probabilities = getProbabilityEntries(evidence);

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
    </div>
  );
};

export const CrawlerResultsView: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<CrawlerUser[]>([]);
  const [usersCursor, setUsersCursor] = useState<string | null>(null);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState("");

  const [selectedUser, setSelectedUser] = useState<CrawlerUser | null>(null);
  const [userRuns, setUserRuns] = useState<CrawlerUserRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("all");
  const [runsLoading, setRunsLoading] = useState(false);
  const [evidence, setEvidence] = useState<CrawlerEvidence[]>([]);
  const [evidenceCursor, setEvidenceCursor] = useState<string | null>(null);
  const [evidenceTotal, setEvidenceTotal] = useState(0);
  const [evidenceLabelCounts, setEvidenceLabelCounts] = useState<
    Partial<Record<CrawlerModelLabel, number>>
  >({});
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [labelFilter, setLabelFilter] = useState<EvidenceLabelFilter>("all");
  const [showStats, setShowStats] = useState(true);
  const [exporting, setExporting] = useState<"users" | "evidence" | null>(null);

  const loadUsers = async (mode: "replace" | "append" = "replace") => {
    setUsersLoading(true);
    setUsersError("");
    try {
      const response = await getCrawlerUsers({
        status: statusFilter,
        search: search.trim(),
        limit: USER_PAGE_SIZE,
        cursor: mode === "append" ? usersCursor || undefined : undefined,
      });
      setUsers((prev) =>
        mode === "append" ? [...prev, ...response.items] : response.items,
      );
      setUsersCursor(response.nextCursor);
      setUsersTotal(response.total);
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
      setUsersError(error instanceof Error ? error.message : "שגיאה בטעינת משתמשים");
    } finally {
      setUsersLoading(false);
    }
  };

  const loadEvidence = async (mode: "replace" | "append" = "replace") => {
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
      });
      setEvidence((prev) =>
        mode === "append" ? [...prev, ...response.items] : response.items,
      );
      setEvidenceCursor(response.nextCursor);
      setEvidenceTotal(response.total);
      setEvidenceLabelCounts(response.labelCounts || {});
    } catch (error) {
      setEvidenceError(error instanceof Error ? error.message : "שגיאה בטעינת evidence");
    } finally {
      setEvidenceLoading(false);
    }
  };

  const loadUserRuns = async (user: CrawlerUser) => {
    setRunsLoading(true);
    try {
      const response = await getCrawlerUserRuns(user.username_key);
      setUserRuns(response.items);
      setSelectedRunId((current) => {
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
      setUserRuns([]);
      setSelectedRunId(user.latest_run_id || "all");
    } finally {
      setRunsLoading(false);
    }
  };

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      loadUsers("replace");
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [statusFilter, search]);

  useEffect(() => {
    setEvidence([]);
    setEvidenceCursor(null);
    setEvidenceTotal(0);
    setEvidenceLabelCounts({});
    loadEvidence("replace");
  }, [selectedUser?.username_key, selectedRunId, labelFilter]);

  useEffect(() => {
    if (!selectedUser) {
      setUserRuns([]);
      setSelectedRunId("all");
      setLabelFilter("all");
      return;
    }
    setUserRuns([]);
    setSelectedRunId(selectedUser.latest_run_id || "all");
    setLabelFilter("all");
    loadUserRuns(selectedUser);
  }, [selectedUser?.username_key]);

  const selectedScore = selectedUser?.latest_score || {};
  const selectedThresholds = selectedUser?.latest_thresholds || {};
  const selectedRun = userRuns.find((run) => run.run_id === selectedRunId);
  const activeScore = selectedRun?.score || selectedScore;
  const activeThresholds = selectedRun?.thresholds || selectedThresholds;
  const allEvidenceLabelCount = evidenceLabelOrder
    .filter((label): label is CrawlerModelLabel => label !== "all")
    .reduce((sum, label) => sum + (evidenceLabelCounts[label] || 0), 0);
  const activeEvidenceCount =
    labelFilter === "all"
      ? allEvidenceLabelCount || evidenceTotal
      : evidenceLabelCounts[labelFilter] ?? evidenceTotal;

  const selectedKeywords = useMemo(
    () => selectedUser?.discovered_by_keywords || [],
    [selectedUser],
  );

  const handleUsersExport = async () => {
    setExporting("users");
    try {
      await exportCrawlerUsersCsv({ status: statusFilter, search: search.trim() });
    } finally {
      setExporting(null);
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

        <div className="grid grid-cols-1 md:grid-cols-[1fr_220px] gap-3 mt-4">
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
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(520px,1fr)_minmax(420px,0.9fr)] gap-6">
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
            <div className="text-sm font-semibold text-gray-800">
              משתמשים ({users.length}/{usersTotal})
            </div>
            {usersError && <div className="text-sm text-red-600">{usersError}</div>}
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
                    Positive
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Ratio
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">
                    Seen
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {users.map((user) => {
                  const isSelected = selectedUser?.username_key === user.username_key;
                  return (
                    <tr
                      key={user.username_key}
                      onClick={() => setSelectedUser(user)}
                      className={`cursor-pointer hover:bg-blue-50 ${
                        isSelected ? "bg-blue-50" : ""
                      }`}
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        @{user.username}
                      </td>
                      <td className="px-4 py-3">
                        <CrawlerStatusBadge status={user.current_status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {user.latest_score?.positive_count ?? "-"} /{" "}
                        {user.latest_score?.evaluated_count ?? "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {formatPercent(getUserPositiveRatio(user))}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(user.last_seen_at)}
                      </td>
                    </tr>
                  );
                })}
                {!usersLoading && users.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
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
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Profile positive</div>
                      <div className="font-semibold text-gray-900">
                        {activeScore.positive_count ?? "-"} /{" "}
                        {activeScore.evaluated_count ?? "-"}
                      </div>
                    </div>
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Ratio</div>
                      <div className="font-semibold text-gray-900">
                        {formatPercent(activeScore.positive_ratio)}
                      </div>
                    </div>
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Threshold</div>
                      <div className="font-semibold text-gray-900">
                        {formatPercent(activeThresholds.positive_ratio_threshold)}
                      </div>
                    </div>
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Min positive</div>
                      <div className="font-semibold text-gray-900">
                        {activeThresholds.min_positive_tweets ?? "-"}
                      </div>
                    </div>
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Min profile</div>
                      <div className="font-semibold text-gray-900">
                        {activeThresholds.min_profile_evaluated_tweets ?? "-"}
                      </div>
                    </div>
                    <div className="bg-gray-50 border border-gray-100 rounded-md p-3">
                      <div className="text-xs text-gray-500">Filtered evidence</div>
                      <div className="font-semibold text-gray-900">{evidenceTotal}</div>
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
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50">
                {evidenceError && (
                  <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                    {evidenceError}
                  </div>
                )}
                {evidence.map((item) => (
                  <EvidenceItem key={`${item.run_id}-${item.phase}-${item.tweet_key}`} evidence={item} />
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
