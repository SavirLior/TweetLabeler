import React, { useState, useEffect } from "react";
import { User, Tweet, UserRole, LabelOption } from "./types";
import {
  getTweets,
  saveTweet,
  addTweets,
  updateTweets,
  deleteTweet,
} from "./services/dataService";
import { Login } from "./components/Login";
import { StudentView } from "./components/StudentView";
import { AdminView } from "./components/AdminView";
import { LogOut, Database, Lock } from "lucide-react";

const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [tweets, setTweets] = useState<Tweet[]>([]);
  const [isInitialized, setIsInitialized] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  // Load data on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const loadedTweets = await getTweets();
        setTweets(loadedTweets);
      } catch (error) {
        console.error("Failed to load tweets", error);
      } finally {
        setIsInitialized(true);
      }
    };

    loadData();
  }, []);

  const handleLogin = (user: User) => {
    setCurrentUser(user);
  };

  const handleLogout = () => {
    setCurrentUser(null);
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
        // Even if not everyone finished, if there's a disagreement, mark as CONFLICT
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

    // All finished and all agree on non-Skip label - return that label    }

    return first;
  };

  const handleLabelTweet = async (
    tweetId: string,
    label: string,
    features: string[] = []
  ) => {
    if (!currentUser) return;

    // 1. Optimistic Update (Update UI immediately)
    const updatedTweets = tweets.map((tweet) => {
      if (tweet.id === tweetId) {
        const newAnnotations = {
          ...tweet.annotations,
          [currentUser.username]: label,
        };

        // Calculate auto-consensus
        const newFinalLabel = calculateFinalLabel(tweet, newAnnotations);

        return {
          ...tweet,
          annotations: newAnnotations,
          annotationFeatures: {
            ...(tweet.annotationFeatures || {}),
            [currentUser.username]: features,
          },
          annotationTimestamps: {
            ...(tweet.annotationTimestamps || {}),
            [currentUser.username]: Date.now(),
          },
          finalLabel: newFinalLabel,
        };
      }
      return tweet;
    });
    setTweets(updatedTweets);

    // 2. Persist
    const changedTweet = updatedTweets.find((t) => t.id === tweetId);
    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  const handleResetLabel = async (tweetId: string) => {
    if (!currentUser) return;

    // 1. Optimistic Update
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map((tweet) => {
      if (tweet.id === tweetId) {
        const newAnnotations = { ...tweet.annotations };
        delete newAnnotations[currentUser.username];

        const newFeatures = { ...(tweet.annotationFeatures || {}) };
        delete newFeatures[currentUser.username];

        const newTimestamps = { ...(tweet.annotationTimestamps || {}) };
        delete newTimestamps[currentUser.username];

        const newTweet = {
          ...tweet,
          annotations: newAnnotations,
          annotationFeatures: newFeatures,
          annotationTimestamps: newTimestamps,
          finalLabel: undefined,
        };
        changedTweet = newTweet;
        return newTweet;
      }
      return tweet;
    });

    setTweets(updatedTweets);

    // 2. Persist
    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  const handleAdminLabelChange = async (
    tweetId: string,
    studentUsername: string,
    newLabel: string
  ) => {
    // 1. Optimistic
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map((tweet) => {
      if (tweet.id === tweetId) {
        const newAnnotations = {
          ...tweet.annotations,
          [studentUsername]: newLabel,
        };

        const newTweet = {
          ...tweet,
          annotations: newAnnotations,
          annotationTimestamps: {
            ...(tweet.annotationTimestamps || {}),
            [studentUsername]: Date.now(),
          },
          // Re-evaluate consensus based on admin change to student label
          finalLabel: calculateFinalLabel(tweet, newAnnotations),
        };
        changedTweet = newTweet;
        return newTweet;
      }
      return tweet;
    });
    setTweets(updatedTweets);

    // 2. Persist
    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  // NEW: Handle setting the Final Label directly (Admin Override / Resolution)
  const handleSetFinalLabel = async (tweetId: string, finalLabel: string) => {
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map((tweet) => {
      if (tweet.id === tweetId) {
        const newTweet = { ...tweet, finalLabel };
        changedTweet = newTweet;
        return newTweet;
      }
      return tweet;
    });
    setTweets(updatedTweets);

    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  const handleAssignmentChange = async (
    tweetId: string,
    assignedTo: string[]
  ) => {
    // 1. Optimistic
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map((tweet) => {
      if (tweet.id === tweetId) {
        // If assignment changes, reset final label to force re-check
        const newTweet = { ...tweet, assignedTo, finalLabel: undefined };
        changedTweet = newTweet;
        return newTweet;
      }
      return tweet;
    });
    setTweets(updatedTweets);

    // 2. Persist
    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  const handleDeleteTweet = async (tweetId: string) => {
    // 1. Optimistic
    const updatedTweets = tweets.filter((t) => t.id !== tweetId);
    setTweets(updatedTweets);

    // 2. Persist
    await deleteTweet(tweetId);
  };

  const handleDeleteAllTweets = async () => {
    // 1. Optimistic
    setTweets([]);

    // 2. Persist - delete all tweets
    const allTweetIds = tweets.map((t) => t.id);
    for (const id of allTweetIds) {
      await deleteTweet(id);
    }
  };

  const handleBulkUpdateTweets = async (updatedList: Tweet[]) => {
    // 1. Optimistic
    // Create a map for faster lookup
    const updatesMap = new Map(updatedList.map((t) => [t.id, t]));
    const newTweetsState = tweets.map((t) => {
      return updatesMap.has(t.id) ? updatesMap.get(t.id)! : t;
    });
    setTweets(newTweetsState);

    // 2. Persist
    await updateTweets(updatedList);
  };

  const handleAddTweets = async (newTweets: Tweet[]) => {
    // 1. Optimistic
    const updatedTweets = [...tweets, ...newTweets];
    setTweets(updatedTweets);
    // 2. Persist
    await addTweets(newTweets);
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

      {/* Main Content */}
      <main className="py-6">
        {currentUser.role === UserRole.Admin ? (
          <AdminView
            tweets={tweets}
            onAdminLabelChange={handleAdminLabelChange}
            onAddTweets={handleAddTweets}
            onBulkUpdateTweets={handleBulkUpdateTweets}
            onDeleteTweet={handleDeleteTweet}
            onUpdateAssignment={handleAssignmentChange}
            onSetFinalLabel={handleSetFinalLabel}
            onDeleteAllTweets={handleDeleteAllTweets}
          />
        ) : (
          <StudentView
            user={currentUser}
            tweets={tweets}
            onLabelTweet={handleLabelTweet}
            onResetLabel={handleResetLabel}
          />
        )}
      </main>

      {/* Password Change Modal */}
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
