import React, { useEffect, useMemo, useState } from "react";
import { User, Tweet, UserRole, LabelOption } from "./types";
import {
  addTweets,
  deleteAllTweets,
  deleteTweet,
  getTweetPage,
  getTweetRounds,
  saveAnnotation,
  saveTweet,
  updateTweets,
} from "./services/dataService";
import { Login } from "./components/Login";
import { StudentView } from "./components/StudentView";
import { AdminView } from "./components/AdminView";
import { LogOut, Database, Lock, AlertTriangle, Copy, RefreshCw } from "lucide-react";

const PAGE_SIZE = 100;
type StudentTab = "label" | "history" | "mistakes";
type AdminRoundSelection = "ALL" | number;

type RollbackState = {
  tweetsById?: Record<string, Tweet | undefined>;
  visibleIds?: string[];
  nextCursor?: string | null;
  hasMore?: boolean;
};

const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [tweetsById, setTweetsById] = useState<Record<string, Tweet>>({});
  const [visibleIds, setVisibleIds] = useState<string[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [isInitialized, setIsInitialized] = useState(true);
  const [studentActiveTab, setStudentActiveTab] = useState<StudentTab>("label");
  const [adminSelectedRound, setAdminSelectedRound] =
    useState<AdminRoundSelection>("ALL");
  const [adminRoundOptions, setAdminRoundOptions] = useState<number[]>([]);
  const [adminCurrentRound, setAdminCurrentRound] = useState(1);
  const [adminRoundReady, setAdminRoundReady] = useState(true);

  const [hasCriticalError, setHasCriticalError] = useState(false);
  const [lastFailedAction, setLastFailedAction] = useState<any>(null);

  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  const tweets = useMemo(
    () =>
      visibleIds
        .map((id) => tweetsById[id])
        .filter((tweet): tweet is Tweet => Boolean(tweet)),
    [tweetsById, visibleIds],
  );

  const currentAppRound = useMemo(() => {
    if (tweets.length === 0) return 1;
    return Math.max(...tweets.map((t) => t.round || 1));
  }, [tweets]);

  const displayedCurrentRound =
    currentUser?.role === UserRole.Admin ? adminCurrentRound : currentAppRound;

  const mergePage = (items: Tweet[], mode: "replace" | "append") => {
    setTweetsById((prev) => {
      const next = mode === "replace" ? {} : { ...prev };
      items.forEach((tweet) => {
        next[tweet.id] = tweet;
      });
      return next;
    });

    setVisibleIds((prev) => {
      if (mode === "replace") {
        return items.map((tweet) => tweet.id);
      }

      const seen = new Set(prev);
      const appended = [...prev];
      items.forEach((tweet) => {
        if (!seen.has(tweet.id)) {
          seen.add(tweet.id);
          appended.push(tweet.id);
        }
      });
      return appended;
    });
  };

  const snapshotTweets = (ids: string[]): Record<string, Tweet | undefined> => {
    const snapshot: Record<string, Tweet | undefined> = {};
    ids.forEach((id) => {
      snapshot[id] = tweetsById[id];
    });
    return snapshot;
  };

  const applyRollback = (rollbackState: RollbackState) => {
    if (rollbackState.tweetsById) {
      setTweetsById((prev) => {
        const next = { ...prev };
        Object.entries(rollbackState.tweetsById || {}).forEach(([id, tweet]) => {
          if (tweet === undefined) {
            delete next[id];
          } else {
            next[id] = tweet;
          }
        });
        return next;
      });
    }
    if (rollbackState.visibleIds) {
      setVisibleIds(rollbackState.visibleIds);
    }
    if (rollbackState.nextCursor !== undefined) {
      setNextCursor(rollbackState.nextCursor);
    }
    if (rollbackState.hasMore !== undefined) {
      setHasMore(rollbackState.hasMore);
    }
  };

  const executeSafeRequest = async (
    apiCall: () => Promise<any>,
    rollbackState: RollbackState,
    actionData: any,
  ) => {
    if (hasCriticalError) return;

    try {
      localStorage.setItem(
        "pending_action_backup",
        JSON.stringify({
          timestamp: new Date().toISOString(),
          user: currentUser?.username,
          ...actionData,
        }),
      );

      await apiCall();
      localStorage.removeItem("pending_action_backup");
    } catch (error) {
      console.error("CRITICAL API FAILURE - SYSTEM LOCKED", error);
      setLastFailedAction(actionData);
      applyRollback(rollbackState);
      setHasCriticalError(true);
    }
  };

  const handleLogin = (user: User) => {
    setCurrentUser(user);
    setStudentActiveTab("label");
    if (user.role === UserRole.Admin) {
      setAdminRoundReady(false);
      setAdminSelectedRound("ALL");
    } else {
      setAdminRoundReady(true);
    }
    setHasCriticalError(false);
    setLastFailedAction(null);
  };

  const handleLogout = () => {
    setCurrentUser(null);
    setTweetsById({});
    setVisibleIds([]);
    setNextCursor(null);
    setHasMore(false);
    setIsInitialized(true);
    setStudentActiveTab("label");
    setAdminSelectedRound("ALL");
    setAdminRoundOptions([]);
    setAdminCurrentRound(1);
    setAdminRoundReady(true);
  };

  const loadAdminRoundMetadata = async (
    signal?: AbortSignal,
    options?: { resetSelection?: boolean },
  ) => {
    const roundsData = await getTweetRounds(signal);
    if (signal?.aborted) return;

    const normalizedRounds =
      roundsData.rounds && roundsData.rounds.length > 0
        ? [...roundsData.rounds].sort((a, b) => a - b)
        : [1];
    const nextCurrentRound =
      roundsData.currentRound || normalizedRounds[normalizedRounds.length - 1] || 1;

    setAdminRoundOptions(normalizedRounds);
    setAdminCurrentRound(nextCurrentRound);
    if (options?.resetSelection) {
      setAdminSelectedRound(nextCurrentRound);
    } else {
      setAdminSelectedRound((prev) => {
        if (prev === "ALL") return prev;
        return normalizedRounds.includes(prev) ? prev : nextCurrentRound;
      });
    }
    setAdminRoundReady(true);
  };

  const calculateFinalLabel = (
    tweet: Tweet,
    newAnnotations: Record<string, string>,
  ): string | undefined => {
    if (tweet.finalLabel && tweet.finalLabel !== "CONFLICT") {
      return tweet.finalLabel;
    }

    const assigned = tweet.assignedTo || [];
    if (assigned.length === 0) return undefined;

    const labels = assigned.map((u) => newAnnotations[u]).filter(Boolean);
    if (labels.length === 0) return undefined;

    if (labels.length > 1) {
      const first = labels[0];
      const hasDisagreement = !labels.every((l) => l === first);
      if (hasDisagreement) {
        return "CONFLICT";
      }
    }

    const first = labels[0];
    if (first === LabelOption.Skip && labels.length > 0) {
      return "CONFLICT";
    }

    if (labels.length < assigned.length) {
      return tweet.finalLabel;
    }

    return first;
  };

  const isConflictLikeFinalLabel = (value?: string) =>
    value === "CONFLICT" || value === LabelOption.Skip;

  const isResolvedFinalLabel = (value?: string) =>
    Boolean(value && value !== "CONFLICT" && value !== LabelOption.Skip);

  const withConflictLifecycle = (
    previousTweet: Tweet,
    nextTweet: Tweet,
    nextFinalLabel: string | undefined,
  ): Tweet => {
    const wasConflictAlready =
      previousTweet.wasInConflict || isConflictLikeFinalLabel(previousTweet.finalLabel);

    if (isConflictLikeFinalLabel(nextFinalLabel)) {
      return {
        ...nextTweet,
        wasInConflict: true,
        conflictHistoryDismissed: false,
        conflictDetectedAt: previousTweet.conflictDetectedAt ?? Date.now(),
        conflictResolvedAt: undefined,
      };
    }

    if (wasConflictAlready && isResolvedFinalLabel(nextFinalLabel)) {
      return {
        ...nextTweet,
        wasInConflict: true,
        conflictResolvedAt: previousTweet.conflictResolvedAt ?? Date.now(),
      };
    }

    return nextTweet;
  };

  const buildTweetsQuery = () => {
    if (!currentUser) {
      return { limit: PAGE_SIZE };
    }

    if (currentUser.role === UserRole.Student) {
      return studentActiveTab === "mistakes"
        ? { limit: PAGE_SIZE, mistakesFor: currentUser.username }
        : { limit: PAGE_SIZE, assignedTo: currentUser.username };
    }

    if (adminSelectedRound === "ALL") {
      return { limit: PAGE_SIZE };
    }

    return { limit: PAGE_SIZE, round: adminSelectedRound };
  };

  const loadTweetsFromApi = async (
    options: {
      signal?: AbortSignal;
      blocking?: boolean;
      lockOnError?: boolean;
    } = {},
  ) => {
    if (!currentUser) {
      return;
    }
    if (currentUser.role === UserRole.Admin && !adminRoundReady) {
      return;
    }

    const { signal, blocking = true, lockOnError = true } = options;
    const query = buildTweetsQuery();

    if (blocking) {
      setIsInitialized(false);
      setTweetsById({});
      setVisibleIds([]);
      setNextCursor(null);
      setHasMore(false);
    }

    setIsFetching(true);

    try {
      const firstPage = await getTweetPage(query, signal);
      if (signal?.aborted) return;

      mergePage(firstPage.items, "replace");
      setNextCursor(firstPage.nextCursor);
      setHasMore(firstPage.hasMore);
      if (blocking) {
        setIsInitialized(true);
      }

      let cursor = firstPage.nextCursor ?? undefined;
      let more = firstPage.hasMore;
      while (more && cursor && !signal?.aborted) {
        const nextPage = await getTweetPage(
          { ...query, cursor, limit: PAGE_SIZE },
          signal,
        );
        if (signal?.aborted) return;
        mergePage(nextPage.items, "append");
        cursor = nextPage.nextCursor ?? undefined;
        more = nextPage.hasMore;
        setNextCursor(nextPage.nextCursor);
        setHasMore(nextPage.hasMore);
      }
    } catch (error) {
      if (!signal?.aborted) {
        console.error("Failed to load tweets", error);
        if (lockOnError) {
          setHasCriticalError(true);
        }
        if (blocking) {
          setIsInitialized(true);
        }
      }
      return;
    }

    if (!signal?.aborted) {
      setIsFetching(false);
    }
  };

  const handleRefreshTweets = async () => {
    await loadTweetsFromApi({ blocking: false, lockOnError: false });
  };

  useEffect(() => {
    if (!currentUser) {
      return;
    }

    if (currentUser.role !== UserRole.Admin) {
      setAdminRoundReady(true);
      return;
    }

    const controller = new AbortController();
    setAdminRoundReady(false);

    loadAdminRoundMetadata(controller.signal, { resetSelection: true }).catch((error) => {
      if (!controller.signal.aborted) {
        console.error("Failed to load admin rounds metadata", error);
        setAdminRoundOptions([1]);
        setAdminCurrentRound(1);
        setAdminSelectedRound(1);
        setAdminRoundReady(true);
      }
    });

    return () => controller.abort();
  }, [currentUser]);

  useEffect(() => {
    if (!currentUser) {
      return;
    }

    const controller = new AbortController();
    loadTweetsFromApi({ signal: controller.signal, blocking: true, lockOnError: true });

    return () => controller.abort();
  }, [currentUser, studentActiveTab, adminSelectedRound, adminRoundReady]);

  const handleLabelTweet = async (
    tweetId: string,
    label: string,
    features: string[] = [],
  ) => {
    if (!currentUser || hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const newAnnotations = {
      ...currentTweet.annotations,
      [currentUser.username]: label,
    };
    const rawOptimisticTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationFeatures: {
        ...(currentTweet.annotationFeatures || {}),
        [currentUser.username]: features,
      },
      annotationTimestamps: {
        ...(currentTweet.annotationTimestamps || {}),
        [currentUser.username]: Date.now(),
      },
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };
    const optimisticTweet = withConflictLifecycle(
      currentTweet,
      rawOptimisticTweet,
      rawOptimisticTweet.finalLabel,
    );

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const response = await saveAnnotation(
          tweetId,
          currentUser.username,
          label,
          features,
        );
        setTweetsById((prev) => {
          const latest = prev[tweetId];
          if (!latest) return prev;
          return {
            ...prev,
            [tweetId]: {
              ...latest,
              finalLabel: response.finalLabel,
              v: response.version,
            },
          };
        });
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "LABEL_TWEET", tweetId, label, username: currentUser.username },
    );
  };

  const handleResetLabel = async (tweetId: string) => {
    if (!currentUser || hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    if (currentUser.role === UserRole.Student && (currentTweet.round || 1) !== currentAppRound) {
      alert(`לא ניתן לתקן תיוג מסבב ישן (סבב ${currentTweet.round || 1}). הסבב הנוכחי הוא ${currentAppRound}.`);
      return;
    }

    const newAnnotations = { ...currentTweet.annotations };
    const newFeatures = { ...(currentTweet.annotationFeatures || {}) };
    const newTimestamps = { ...(currentTweet.annotationTimestamps || {}) };

    delete newAnnotations[currentUser.username];
    delete newFeatures[currentUser.username];
    delete newTimestamps[currentUser.username];

    const rawOptimisticTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationFeatures: newFeatures,
      annotationTimestamps: newTimestamps,
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };
    const optimisticTweet = withConflictLifecycle(
      currentTweet,
      rawOptimisticTweet,
      rawOptimisticTweet.finalLabel,
    );

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "RESET_LABEL", tweetId, username: currentUser.username },
    );
  };

  const handleAdminLabelChange = async (
    tweetId: string,
    studentUsername: string,
    newLabel: string,
  ) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const newAnnotations = {
      ...currentTweet.annotations,
      [studentUsername]: newLabel,
    };
    const rawOptimisticTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationTimestamps: {
        ...(currentTweet.annotationTimestamps || {}),
        [studentUsername]: Date.now(),
      },
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };
    const optimisticTweet = withConflictLifecycle(
      currentTweet,
      rawOptimisticTweet,
      rawOptimisticTweet.finalLabel,
    );

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "ADMIN_LABEL_CHANGE", tweetId, studentUsername, newLabel },
    );
  };

  const handleAdminDeleteVote = async (
    tweetId: string,
    studentUsername: string,
  ) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const newAnnotations = { ...currentTweet.annotations };
    const newFeatures = { ...(currentTweet.annotationFeatures || {}) };
    const newTimestamps = { ...(currentTweet.annotationTimestamps || {}) };
    delete newAnnotations[studentUsername];
    delete newFeatures[studentUsername];
    delete newTimestamps[studentUsername];

    const rawOptimisticTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationFeatures: newFeatures,
      annotationTimestamps: newTimestamps,
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };
    const optimisticTweet = withConflictLifecycle(
      currentTweet,
      rawOptimisticTweet,
      rawOptimisticTweet.finalLabel,
    );

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "ADMIN_DELETE_VOTE", tweetId, studentUsername },
    );
  };

  const handleSetFinalLabel = async (
    tweetId: string,
    finalLabel: string,
    resolutionReason?: string,
  ) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const normalizedReason = resolutionReason?.trim() || undefined;
    const rawOptimisticTweet: Tweet = {
      ...currentTweet,
      finalLabel,
      resolutionReason: normalizedReason,
    };
    const optimisticTweet = withConflictLifecycle(
      currentTweet,
      rawOptimisticTweet,
      finalLabel,
    );

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "SET_FINAL_LABEL", tweetId, finalLabel, resolutionReason: normalizedReason },
    );
  };

  const handleAssignmentChange = async (
    tweetId: string,
    assignedTo: string[],
  ) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const optimisticTweet: Tweet = {
      ...currentTweet,
      assignedTo,
      finalLabel: undefined,
    };

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "ASSIGNMENT_CHANGE", tweetId, assignedTo },
    );
  };

  const handleRemoveFromConflictArchive = async (tweetId: string) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const optimisticTweet: Tweet = {
      ...currentTweet,
      wasInConflict: false,
      conflictHistoryDismissed: true,
      conflictDetectedAt: undefined,
      conflictResolvedAt: undefined,
    };

    setTweetsById((prev) => ({ ...prev, [tweetId]: optimisticTweet }));

    await executeSafeRequest(
      async () => {
        const savedTweet = await saveTweet(optimisticTweet);
        setTweetsById((prev) => ({ ...prev, [tweetId]: savedTweet }));
      },
      { tweetsById: snapshotTweets([tweetId]) },
      { type: "REMOVE_CONFLICT_ARCHIVE", tweetId },
    );
  };

  const handleDeleteTweet = async (tweetId: string) => {
    if (hasCriticalError) return;

    const rollbackState: RollbackState = {
      tweetsById: snapshotTweets([tweetId]),
      visibleIds: visibleIds,
    };

    setTweetsById((prev) => {
      const next = { ...prev };
      delete next[tweetId];
      return next;
    });
    setVisibleIds((prev) => prev.filter((id) => id !== tweetId));

    await executeSafeRequest(
      () => deleteTweet(tweetId),
      rollbackState,
      { type: "DELETE_TWEET", tweetId },
    );
  };

  const handleDeleteAllTweets = async () => {
    if (hasCriticalError) return;

    const rollbackState: RollbackState = {
      tweetsById: { ...tweetsById },
      visibleIds: [...visibleIds],
      nextCursor,
      hasMore,
    };

    setTweetsById({});
    setVisibleIds([]);
    setNextCursor(null);
    setHasMore(false);

    await executeSafeRequest(
      () => deleteAllTweets(),
      rollbackState,
      { type: "DELETE_ALL_TWEETS" },
    );

    if (currentUser?.role === UserRole.Admin) {
      loadAdminRoundMetadata(undefined, { resetSelection: false }).catch((error) => {
        console.error("Failed to refresh rounds metadata after delete all", error);
      });
    }
  };

  const handleBulkUpdateTweets = async (updatedList: Tweet[]) => {
    if (hasCriticalError) return;

    const changedIds = updatedList.map((tweet) => tweet.id);
    const updatedMap = Object.fromEntries(updatedList.map((tweet) => [tweet.id, tweet]));

    setTweetsById((prev) => ({ ...prev, ...updatedMap }));

    await executeSafeRequest(
      async () => {
        const savedTweets = await updateTweets(updatedList);
        if (savedTweets.length === 0) return;
        const savedMap = Object.fromEntries(savedTweets.map((tweet) => [tweet.id, tweet]));
        setTweetsById((prev) => ({ ...prev, ...savedMap }));
      },
      { tweetsById: snapshotTweets(changedIds) },
      { type: "BULK_UPDATE_TWEETS", count: updatedList.length },
    );
  };

  const handleAddTweets = async (newTweets: Tweet[]) => {
    if (hasCriticalError) return;

    const previousIds = [...visibleIds];
    const newIds = newTweets.map((tweet) => tweet.id);
    const withDefaults = newTweets.map((tweet) => ({
      ...tweet,
      v: tweet.v ?? 0,
    }));
    const appendedMap = Object.fromEntries(withDefaults.map((tweet) => [tweet.id, tweet]));

    setTweetsById((prev) => ({ ...prev, ...appendedMap }));
    setVisibleIds((prev) => [...prev, ...newIds.filter((id) => !prev.includes(id))]);

    await executeSafeRequest(
      () => addTweets(withDefaults),
      { tweetsById: snapshotTweets(newIds), visibleIds: previousIds },
      { type: "ADD_TWEETS", count: withDefaults.length },
    );

    if (currentUser?.role === UserRole.Admin) {
      loadAdminRoundMetadata(undefined, { resetSelection: false }).catch((error) => {
        console.error("Failed to refresh rounds metadata after add", error);
      });
    }
  };

  const handleChangePassword = async () => {
    setPasswordError("");
    setPasswordSuccess("");

    if (!currentPassword || !newPassword || !confirmPassword) {
      setPasswordError("כל השדות נדרשים");
      return;
    }
    if (newPassword.length < 6) {
      setPasswordError("הסיסמה החדשה חייבת להכיל לפחות 6 תווים");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("הסיסמאות החדשות לא תואמות");
      return;
    }
    if (currentPassword === newPassword) {
      setPasswordError("הסיסמה החדשה זהה לסיסמה הנוכחית");
      return;
    }

    try {
      const response = await fetch("/api/users/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: currentUser?.username || "",
          currentPassword,
          newPassword,
        }),
      });

      const data = await response.json();
      if (response.ok) {
        setPasswordSuccess("הסיסמה שונתה בהצלחה!");
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setTimeout(() => {
          setShowPasswordModal(false);
          setPasswordSuccess("");
        }, 2000);
      } else {
        setPasswordError(data.error || "שגיאה בשינוי הסיסמה");
      }
    } catch (error) {
      setPasswordError("שגיאה בתקשורת עם השרת");
    }
  };

  const resetPasswordForm = () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setPasswordError("");
    setPasswordSuccess("");
    setShowPasswordModal(false);
  };

  if (hasCriticalError) {
    const errorDetails = JSON.stringify(
      lastFailedAction || "Unknown Error",
      null,
      2,
    );

    const handleCopyError = () => {
      navigator.clipboard.writeText(errorDetails);
      alert("פרטי השגיאה הועתקו ללוח!");
    };

    return (
      <div
        className="min-h-screen bg-gray-900 flex items-center justify-center p-6 text-white"
        dir="rtl"
      >
        <div className="bg-red-900/20 border-2 border-red-500 p-8 rounded-2xl max-w-2xl w-full shadow-2xl backdrop-blur-md">
          <div className="flex items-center gap-4 mb-6">
            <AlertTriangle className="w-12 h-12 text-red-500" />
            <h1 className="text-3xl font-bold">המערכת ננעלה להגנה על המידע</h1>
          </div>

          <p className="text-lg mb-6 text-gray-300">
            בבקשה תפנו לצוות מדעי המחשב. זוהתה תקלה בתקשורת מול השרת. כדי לוודא שאף תיוג לא ילך לאיבוד, עצרנו את האפשרות להמשיך לעבוד.
          </p>

          <div className="bg-black/40 p-4 rounded-lg mb-6 font-mono text-sm border border-red-800/50">
            <div className="flex justify-between items-center mb-2">
              <p className="text-red-400">// פרטי השגיאה האחרונה לצוות הפיתוח:</p>
              <button
                onClick={handleCopyError}
                className="flex items-center gap-1 text-xs bg-red-500/20 hover:bg-red-500/40 text-red-200 px-3 py-1.5 rounded border border-red-500/30 transition-all"
              >
                <Copy className="w-3 h-3" />
                העתק שגיאה
              </button>
            </div>
            <pre className="overflow-auto max-h-40 text-left" dir="ltr">
              {errorDetails}
            </pre>
          </div>

          <div className="flex flex-col sm:flex-row gap-4">
            <button
              onClick={() => window.location.reload()}
              className="flex-1 bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded-xl transition-all"
            >
              רענן עמוד (נסה להתחבר מחדש)
            </button>
          </div>
          <p className="mt-6 text-sm text-gray-400 text-center">
            אל דאגה, התיוגים שכבר אושרו בשרת שמורים. התיוג האחרון שנכשל מופיע
            למעלה.
          </p>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return <Login onLogin={handleLogin} />;
  }

  if (!isInitialized) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        טוען נתונים...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100 font-sans" dir="rtl">
      <nav className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <span className="text-xl font-bold text-blue-600">TweetLabeler</span>
              <span className="mr-4 px-2 py-1 bg-blue-100 rounded text-xs font-medium text-blue-800 border border-blue-200">
                סבב נוכחי: {displayedCurrentRound}
              </span>
              <span className="mr-4 px-2 py-1 bg-gray-100 rounded text-xs font-medium text-gray-600">
                גרסת מחקר v2.0
              </span>
              {isFetching && (
                <span className="mr-3 text-xs text-gray-500">טוען עמודים נוספים...</span>
              )}
            </div>
            <div className="flex items-center gap-4">
              <div
                title="MongoDB"
                className="text-gray-600 bg-gray-50 p-1.5 rounded-full flex items-center gap-2 px-3"
              >
                <Database className="w-4 h-4" />
                <span className="text-xs font-medium">MongoDB</span>
              </div>

              <div className="text-sm text-right hidden sm:block">
                <p className="font-medium text-gray-900">{currentUser.username}</p>
                <p className="text-xs text-gray-500">
                  {currentUser.role === UserRole.Admin ? "מנהל מערכת" : "סטודנט"}
                </p>
              </div>
              <button
                onClick={() => setShowPasswordModal(true)}
                className="p-2 rounded-full text-gray-500 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                title="שינוי סיסמה"
              >
                <Lock className="w-5 h-5" />
              </button>
              <button
                onClick={handleRefreshTweets}
                className="p-2 rounded-full text-gray-500 hover:text-green-600 hover:bg-green-50 transition-colors"
                title="רענן נתונים"
                disabled={isFetching}
              >
                <RefreshCw className={`w-5 h-5 ${isFetching ? "animate-spin" : ""}`} />
              </button>
              <button
                onClick={handleLogout}
                className="p-2 rounded-full text-gray-500 hover:text-red-600 hover:bg-red-50 transition-colors"
                title="התנתק"
              >
                <LogOut className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </nav>

      <main className="py-6">
        {currentUser.role === UserRole.Admin ? (
          <AdminView
            tweets={tweets}
            currentAppRound={displayedCurrentRound}
            selectedGlobalRound={adminSelectedRound}
            availableGlobalRounds={adminRoundOptions}
            onSelectedGlobalRoundChange={setAdminSelectedRound}
            onAdminLabelChange={handleAdminLabelChange}
            onAdminDeleteVote={handleAdminDeleteVote}
            onAddTweets={handleAddTweets}
            onBulkUpdateTweets={handleBulkUpdateTweets}
            onDeleteTweet={handleDeleteTweet}
            onUpdateAssignment={handleAssignmentChange}
            onSetFinalLabel={handleSetFinalLabel}
            onRemoveResolvedConflict={handleRemoveFromConflictArchive}
            onDeleteAllTweets={handleDeleteAllTweets}
          />
        ) : (
          <StudentView
            user={currentUser}
            tweets={tweets}
            currentAppRound={currentAppRound}
            activeTab={studentActiveTab}
            onActiveTabChange={setStudentActiveTab}
            onLabelTweet={handleLabelTweet}
            onResetLabel={handleResetLabel}
          />
        )}
      </main>

      {showPasswordModal && currentUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="flex items-center justify-between p-6 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Lock className="w-5 h-5 text-blue-600" />
                <h2 className="text-xl font-bold text-gray-900">שינוי סיסמה</h2>
              </div>
              <button onClick={resetPasswordForm} className="text-gray-500 hover:text-gray-700">
                ✕
              </button>
            </div>

            <div className="p-6 space-y-4">
              {passwordError && (
                <div className="bg-red-50 text-red-700 p-3 rounded-lg text-sm border border-red-200">
                  {passwordError}
                </div>
              )}
              {passwordSuccess && (
                <div className="bg-green-50 text-green-700 p-3 rounded-lg text-sm border border-green-200">
                  {passwordSuccess}
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  סיסמה נוכחית
                </label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="הזן סיסמה נוכחית"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  סיסמה חדשה
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="הזן סיסמה חדשה (לפחות 6 תווים)"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  אישור סיסמה חדשה
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="אשר סיסמה חדשה"
                />
              </div>
              <div className="flex gap-3 pt-4">
                <button
                  onClick={resetPasswordForm}
                  className="flex-1 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
                >
                  ביטול
                </button>
                <button
                  onClick={handleChangePassword}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
                >
                  שנה סיסמה
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
