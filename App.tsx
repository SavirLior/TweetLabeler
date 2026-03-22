import React, { useState, useEffect, useMemo, useRef } from "react";
import { User, Tweet, UserRole, LabelOption } from "./types";
import {
  getTweetPage,
  saveTweet,
  addTweets,
  updateTweets,
  deleteTweet,
  deleteAllTweets,
  saveAnnotation
} from "./services/dataService";
import { Login } from "./components/Login";
import { StudentView } from "./components/StudentView";
import { AdminView } from "./components/AdminView";
import { LogOut, Database, Lock, AlertTriangle, Copy } from "lucide-react"; // הוספנו את האייקון Copy

const App: React.FC = () => {
  const PAGE_SIZE = 100;

  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [tweetsById, setTweetsById] = useState<Record<string, Tweet>>({});
  const [visibleIds, setVisibleIds] = useState<string[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isFetchingTweets, setIsFetchingTweets] = useState(false);
  const [isInitialized] = useState(true);

  // System lock states to prevent data loss
  const [hasCriticalError, setHasCriticalError] = useState(false);
  const [lastFailedAction, setLastFailedAction] = useState<any>(null);

  // Password modal states
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  const inFlightTweetsRequestRef = useRef<AbortController | null>(null);

  const tweets = useMemo(() => {
    return visibleIds
      .map((id) => tweetsById[id])
      .filter((tweet): tweet is Tweet => Boolean(tweet));
  }, [visibleIds, tweetsById]);

  const mergeTweetsPage = (items: Tweet[], reset: boolean = false) => {
    setTweetsById((prev) => {
      const next = reset ? {} : { ...prev };
      for (const tweet of items) {
        next[tweet.id] = tweet;
      }
      return next;
    });

    setVisibleIds((prev) => {
      if (reset) {
        return items.map((tweet) => tweet.id);
      }
      const seen = new Set(prev);
      const merged = [...prev];
      for (const tweet of items) {
        if (!seen.has(tweet.id)) {
          merged.push(tweet.id);
          seen.add(tweet.id);
        }
      }
      return merged;
    });
  };

  const resetTweetsState = () => {
    setTweetsById({});
    setVisibleIds([]);
    setNextCursor(null);
    setHasMore(false);
  };

  const loadTweetsPage = async ({
    reset = false,
    cursor,
    user,
  }: {
    reset?: boolean;
    cursor?: string | null;
    user?: User | null;
  } = {}) => {
    const effectiveUser = user ?? currentUser;
    if (!effectiveUser || hasCriticalError || isFetchingTweets) {
      return;
    }

    if (reset) {
      inFlightTweetsRequestRef.current?.abort();
      resetTweetsState();
    }

    const controller = new AbortController();
    inFlightTweetsRequestRef.current = controller;
    setIsFetchingTweets(true);

    try {
      // On initial/reset load, fetch all pages for the current scope:
      // - Admin: all tweets
      // - Student: only tweets assigned to that student
      if (reset && !cursor) {
        let currentCursor: string | undefined = undefined;
        let isFirstPage = true;

        while (true) {
          const page = await getTweetPage(
            {
              limit: PAGE_SIZE,
              cursor: currentCursor,
              assignedTo:
                effectiveUser.role === UserRole.Student
                  ? effectiveUser.username
                  : undefined,
            },
            controller.signal
          );

          mergeTweetsPage(page.items, isFirstPage);
          isFirstPage = false;

          if (!page.hasMore || !page.nextCursor) {
            setNextCursor(null);
            setHasMore(false);
            break;
          }
          currentCursor = page.nextCursor;
        }
      } else {
        const page = await getTweetPage(
          {
            limit: PAGE_SIZE,
            cursor: cursor || undefined,
            assignedTo:
              effectiveUser.role === UserRole.Student
                ? effectiveUser.username
                : undefined,
          },
          controller.signal
        );

        mergeTweetsPage(page.items, reset);
        setNextCursor(page.nextCursor);
        setHasMore(page.hasMore);
      }
    } catch (error: any) {
      // Ignore aborted request: the newest request will own the state.
      if (error?.name === "AbortError") {
        return;
      }
      console.error("Failed to load tweets page", error);
      setHasCriticalError(true);
    } finally {
      if (inFlightTweetsRequestRef.current === controller) {
        inFlightTweetsRequestRef.current = null;
      }
      setIsFetchingTweets(false);
    }
  };

  useEffect(() => {
    if (!currentUser) {
      inFlightTweetsRequestRef.current?.abort();
      resetTweetsState();
      return;
    }
    void loadTweetsPage({ reset: true, user: currentUser });
  }, [currentUser]);

  const handleLogin = (user: User) => setCurrentUser(user);
  const handleLogout = () => {
    inFlightTweetsRequestRef.current?.abort();
    setCurrentUser(null);
  };

  const handleLoadMoreTweets = async () => {
    if (
      !currentUser ||
      (currentUser.role === UserRole.Admin || currentUser.role === UserRole.Student) ||
      !hasMore ||
      !nextCursor ||
      isFetchingTweets
    ) {
      return;
    }
    await loadTweetsPage({ cursor: nextCursor, user: currentUser });
  };

  // Helper to check consensus
  const calculateFinalLabel = (
    tweet: Tweet,
    newAnnotations: Record<string, string>
  ): string | undefined => {
    // If admin already set a final label, don't override it with auto-consensus
    if (tweet.finalLabel && tweet.finalLabel !== "CONFLICT") {
      return tweet.finalLabel;
    }

    const assigned = tweet.assignedTo || [];
    if (assigned.length === 0) return undefined;

    // Get labels from students who have already labeled
    const labels = assigned.map((u) => newAnnotations[u]).filter(Boolean);

    // If no one has labeled yet, return undefined
    if (labels.length === 0) return undefined;

    // Check if there's ANY disagreement among those who DID label
    if (labels.length > 1) {
      const first = labels[0];
      const hasDisagreement = !labels.every((l) => l === first);

      if (hasDisagreement) {
        return "CONFLICT";
      }
    }

    // If everyone who labeled agrees on "Skip/Unsure", mark as CONFLICT
    const first = labels[0];
    if (first === LabelOption.Skip && labels.length > 0) {
      return "CONFLICT";
    }

    // If not everyone finished yet, don't resolve yet
    if (labels.length < assigned.length) return tweet.finalLabel;

    return first;
  };

  /**
   * Centralized safe request handler to prevent data loss.
   * Locks the UI and rolls back only touched entities if the API call fails.
   */
  const executeSafeRequest = async <T,>(
    apiCall: () => Promise<T>,
    rollbackState: () => void,
    actionData: any
  ): Promise<T | undefined> => {
    // Prevent execution if system is already locked
    if (hasCriticalError) return undefined;

    try {
      // Temporary local backup in case the browser closes during a server failure
      localStorage.setItem("pending_action_backup", JSON.stringify({
        timestamp: new Date().toISOString(),
        user: currentUser?.username,
        ...actionData
      }));

      const response = await apiCall();
      
      // Clear backup on success
      localStorage.removeItem("pending_action_backup");
      return response;
    } catch (error) {
      console.error("CRITICAL API FAILURE - SYSTEM LOCKED", error);

      // Save failed action details for debugging
      setLastFailedAction(actionData);
      
      // Rollback UI to the previous stable state
      rollbackState();
      
      // Lock the entire application
      setHasCriticalError(true);
      return undefined;
    }
  };

  const handleLabelTweet = async (tweetId: string, label: string, features: string[] = []) => {
    if (!currentUser || hasCriticalError) return;
    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    // Snapshot of touched state for potential rollback
    const previousTweet = { ...currentTweet };
    // Optimistic UI update
    const newAnnotations = { ...currentTweet.annotations, [currentUser.username]: label };
    const newFinalLabel = calculateFinalLabel(currentTweet, newAnnotations);

    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: {
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
        finalLabel: newFinalLabel,
      },
    }));

    // Execute the API call safely
    const response = await executeSafeRequest(
      () => saveAnnotation(tweetId, currentUser.username, label, features, currentTweet.v),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "LABEL_TWEET", tweetId, label, username: currentUser.username }
    );

    if (response) {
      setTweetsById((prev) => {
        const existing = prev[tweetId];
        if (!existing) return prev;
        return {
          ...prev,
          [tweetId]: {
            ...existing,
            finalLabel: response.finalLabel ?? undefined,
            v: response.version ?? existing.v,
          },
        };
      });
    }
  };

  const handleResetLabel = async (tweetId: string) => {
    if (!currentUser || hasCriticalError) return;
    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const previousTweet = { ...currentTweet };
    const newTweet: Tweet = {
      ...currentTweet,
      annotations: { ...currentTweet.annotations },
      annotationFeatures: { ...(currentTweet.annotationFeatures || {}) },
      annotationTimestamps: { ...(currentTweet.annotationTimestamps || {}) },
      finalLabel: undefined,
    };
    delete newTweet.annotations[currentUser.username];
    delete newTweet.annotationFeatures![currentUser.username];
    delete newTweet.annotationTimestamps![currentUser.username];

    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: newTweet,
    }));

    const response = await executeSafeRequest(
      () => saveTweet(newTweet),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "RESET_LABEL", tweetId, username: currentUser.username }
    );

    if (response?.tweet) {
      setTweetsById((prev) => ({
        ...prev,
        [tweetId]: response.tweet,
      }));
    }
  };

  const handleAdminLabelChange = async (tweetId: string, studentUsername: string, newLabel: string) => {
    if (hasCriticalError) return;
    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const previousTweet = { ...currentTweet };
    const newAnnotations = { ...currentTweet.annotations, [studentUsername]: newLabel };
    const newTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationTimestamps: {
        ...(currentTweet.annotationTimestamps || {}),
        [studentUsername]: Date.now(),
      },
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };

    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: newTweet,
    }));

    const response = await executeSafeRequest(
      () => saveTweet(newTweet),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "ADMIN_LABEL_CHANGE", tweetId, studentUsername, newLabel }
    );

    if (response?.tweet) {
      setTweetsById((prev) => ({
        ...prev,
        [tweetId]: response.tweet,
      }));
    }
  };

  const handleAdminDeleteVote = async (tweetId: string, studentUsername: string) => {
    if (hasCriticalError) return;

    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const previousTweet = { ...currentTweet };
    const newAnnotations = { ...currentTweet.annotations };
    const newFeatures = { ...(currentTweet.annotationFeatures || {}) };
    const newTimestamps = { ...(currentTweet.annotationTimestamps || {}) };

    delete newAnnotations[studentUsername];
    delete newFeatures[studentUsername];
    delete newTimestamps[studentUsername];

    const newTweet: Tweet = {
      ...currentTweet,
      annotations: newAnnotations,
      annotationFeatures: newFeatures,
      annotationTimestamps: newTimestamps,
      finalLabel: calculateFinalLabel(currentTweet, newAnnotations),
    };

    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: newTweet,
    }));

    const response = await executeSafeRequest(
      () => saveTweet(newTweet),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "ADMIN_DELETE_VOTE", tweetId, studentUsername }
    );

    if (response?.tweet) {
      setTweetsById((prev) => ({
        ...prev,
        [tweetId]: response.tweet,
      }));
    }
  };

  const handleSetFinalLabel = async (tweetId: string, finalLabel: string) => {
    if (hasCriticalError) return;
    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const previousTweet = { ...currentTweet };
    const newTweet = { ...currentTweet, finalLabel };
    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: newTweet,
    }));

    const response = await executeSafeRequest(
      () => saveTweet(newTweet),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "SET_FINAL_LABEL", tweetId, finalLabel }
    );

    if (response?.tweet) {
      setTweetsById((prev) => ({
        ...prev,
        [tweetId]: response.tweet,
      }));
    }
  };

  const handleAssignmentChange = async (tweetId: string, assignedTo: string[]) => {
    if (hasCriticalError) return;
    const currentTweet = tweetsById[tweetId];
    if (!currentTweet) return;

    const previousTweet = { ...currentTweet };
    const newTweet = { ...currentTweet, assignedTo, finalLabel: undefined };
    setTweetsById((prev) => ({
      ...prev,
      [tweetId]: newTweet,
    }));

    const response = await executeSafeRequest(
      () => saveTweet(newTweet),
      () =>
        setTweetsById((prev) => ({
          ...prev,
          [tweetId]: previousTweet,
        })),
      { type: "ASSIGNMENT_CHANGE", tweetId, assignedTo }
    );

    if (response?.tweet) {
      setTweetsById((prev) => ({
        ...prev,
        [tweetId]: response.tweet,
      }));
    }
  };

  const handleDeleteTweet = async (tweetId: string) => {
    if (hasCriticalError) return;
    const previousTweet = tweetsById[tweetId];
    const previousIndex = visibleIds.indexOf(tweetId);
    if (!previousTweet) return;

    setTweetsById((prev) => {
      const next = { ...prev };
      delete next[tweetId];
      return next;
    });
    setVisibleIds((prev) => prev.filter((id) => id !== tweetId));

    await executeSafeRequest(
      () => deleteTweet(tweetId),
      () => {
        setTweetsById((prev) => ({ ...prev, [tweetId]: previousTweet }));
        setVisibleIds((prev) => {
          if (previousIndex < 0) return prev;
          const next = [...prev];
          next.splice(previousIndex, 0, tweetId);
          return next;
        });
      },
      { type: "DELETE_TWEET", tweetId }
    );
  };

  const handleDeleteAllTweets = async () => {
    if (hasCriticalError) return;
    const previousTweetsById = { ...tweetsById };
    const previousVisibleIds = [...visibleIds];

    setTweetsById({});
    setVisibleIds([]);
    setHasMore(false);
    setNextCursor(null);

    await executeSafeRequest(
      () => deleteAllTweets(),
      () => {
        setTweetsById(previousTweetsById);
        setVisibleIds(previousVisibleIds);
      },
      { type: "DELETE_ALL_TWEETS" }
    );
  };

  const handleBulkUpdateTweets = async (updatedList: Tweet[]) => {
    if (hasCriticalError) return;
    const previousMap = new Map<string, Tweet>();
    for (const tweet of updatedList) {
      const existing = tweetsById[tweet.id];
      if (existing) {
        previousMap.set(tweet.id, existing);
      }
    }

    setTweetsById((prev) => {
      const next = { ...prev };
      for (const tweet of updatedList) {
        next[tweet.id] = tweet;
      }
      return next;
    });

    const response = await executeSafeRequest(
      () => updateTweets(updatedList),
      () =>
        setTweetsById((prev) => {
          const next = { ...prev };
          previousMap.forEach((tweet, id) => {
            next[id] = tweet;
          });
          return next;
        }),
      { type: "BULK_UPDATE_TWEETS" }
    );

    if (response?.results?.length) {
      setTweetsById((prev) => {
        const next = { ...prev };
        let changed = false;
        for (const result of response.results) {
          if (!result.success || !result.tweetId || result.version === undefined) continue;
          const existing = next[result.tweetId];
          if (!existing) continue;
          next[result.tweetId] = { ...existing, v: result.version };
          changed = true;
        }
        return changed ? next : prev;
      });
    }
  };

  const handleAddTweets = async (newTweets: Tweet[]) => {
    if (hasCriticalError) return;
    const normalizedNewTweets = newTweets.map((tweet) => ({
      ...tweet,
      annotations: tweet.annotations || {},
      annotationFeatures: tweet.annotationFeatures || {},
      annotationTimestamps: tweet.annotationTimestamps || {},
      v: tweet.v ?? 0,
    }));
    const addedIds = normalizedNewTweets.map((tweet) => tweet.id);

    setTweetsById((prev) => {
      const next = { ...prev };
      for (const tweet of normalizedNewTweets) {
        next[tweet.id] = tweet;
      }
      return next;
    });
    setVisibleIds((prev) => {
      const seen = new Set(prev);
      const next = [...prev];
      for (const id of addedIds) {
        if (!seen.has(id)) {
          next.push(id);
          seen.add(id);
        }
      }
      return next;
    });

    await executeSafeRequest(
      () => addTweets(normalizedNewTweets),
      () => {
        setTweetsById((prev) => {
          const next = { ...prev };
          for (const id of addedIds) {
            delete next[id];
          }
          return next;
        });
        setVisibleIds((prev) => prev.filter((id) => !addedIds.includes(id)));
      },
      { type: "ADD_TWEETS", count: newTweets.length }
    );
  };

  // Password handling 
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

  // Render critical error fallback UI
  if (hasCriticalError) {
    const errorDetails = JSON.stringify(lastFailedAction || "Unknown Error", null, 2);

    const handleCopyError = () => {
      navigator.clipboard.writeText(errorDetails);
      alert("פרטי השגיאה הועתקו ללוח!");
    };

    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center p-6 text-white" dir="rtl">
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
            אל דאגה, התיוגים שכבר אושרו בשרת שמורים. התיוג האחרון שנכשל מופיע למעלה.
          </p>
        </div>
      </div>
    );
  }

  if (!isInitialized) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        טוען נתונים...
      </div>
    );
  }

  if (!currentUser) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <div className="min-h-screen bg-gray-100 font-sans" dir="rtl">
      {/* Navbar */}
      <nav className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <span className="text-xl font-bold text-blue-600">
                TweetLabeler
              </span>
              <span className="mr-4 px-2 py-1 bg-gray-100 rounded text-xs font-medium text-gray-600">
                גרסת מחקר v1.0
              </span>
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
                <p className="font-medium text-gray-900">
                  {currentUser.username}
                </p>
                <p className="text-xs text-gray-500">
                  {currentUser.role === UserRole.Admin
                    ? "מנהל מערכת"
                    : "סטודנט"}
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
            onAdminLabelChange={handleAdminLabelChange}
            onAdminDeleteVote={handleAdminDeleteVote}
            onAddTweets={handleAddTweets}
            onBulkUpdateTweets={handleBulkUpdateTweets}
            onDeleteTweet={handleDeleteTweet}
            onUpdateAssignment={handleAssignmentChange}
            onSetFinalLabel={handleSetFinalLabel}
            onDeleteAllTweets={handleDeleteAllTweets}
            hasMoreTweets={false}
            onLoadMoreTweets={handleLoadMoreTweets}
            isLoadingMore={isFetchingTweets}
          />
        ) : (
          <StudentView
            user={currentUser}
            tweets={tweets}
            onLabelTweet={handleLabelTweet}
            onResetLabel={handleResetLabel}
            hasMoreTweets={false}
            onLoadMoreTweets={handleLoadMoreTweets}
            isLoadingMore={isFetchingTweets}
          />
        )}
      </main>

      {/* Password Modal */}
      {showPasswordModal && currentUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="flex items-center justify-between p-6 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Lock className="w-5 h-5 text-blue-600" />
                <h2 className="text-xl font-bold text-gray-900">שינוי סיסמה</h2>
              </div>
              <button
                onClick={resetPasswordForm}
                className="text-gray-500 hover:text-gray-700"
              >
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
