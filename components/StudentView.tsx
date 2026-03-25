import React, { useMemo, useState } from "react";
import { User, Tweet, LabelOption, LABEL_REASONS } from "../types";
import { Button } from "./Button";
import { exportToCSV } from "../services/dataService";
import {
  CheckCircle,
  Clock,
  Save,
  History,
  RotateCcw,
  Download,
  Search,
  Calendar,
  X,
  AlertTriangle,
} from "lucide-react";

interface StudentViewProps {
  user: User;
  tweets: Tweet[];
  currentAppRound: number;
  activeTab: "label" | "history" | "mistakes";
  onActiveTabChange: (tab: "label" | "history" | "mistakes") => void;
  onLabelTweet: (tweetId: string, label: string, features: string[]) => void;   
  onResetLabel: (tweetId: string) => void;
}

export const StudentView: React.FC<StudentViewProps> = ({
  user,
  tweets,
  currentAppRound,
  activeTab,
  onActiveTabChange,
  onLabelTweet,
  onResetLabel,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [historyRoundFilter, setHistoryRoundFilter] = useState<"all" | number>("all");
  const [mistakesRoundFilter, setMistakesRoundFilter] = useState<"all" | number>("all");

  // Modal State
  const [pendingLabel, setPendingLabel] = useState<{
    tweetId: string;
    label: string;
  } | null>(null);
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [skipReason, setSkipReason] = useState("");

  // Filter tweets specifically assigned to this user
  const myTweets = useMemo(() => {
    return tweets.filter((t) => t.assignedTo?.includes(user.username));
  }, [tweets, user.username]);

  const availableMyRounds = useMemo(() => {
    const rounds = Array.from(new Set(myTweets.map((tweet) => tweet.round || 1)));
    return rounds.sort((a, b) => b - a);
  }, [myTweets]);

  // Tweets that have NOT been labeled by this user
  const unlabeledTweets = useMemo(() => {
    return myTweets.filter((t: Tweet) => !t.annotations[user.username]);
  }, [myTweets, user.username]);

  // Tweets that HAVE been labeled by this user, filtered and sorted
  const labeledTweets = useMemo(() => {
    let result = myTweets.filter((t: Tweet) => t.annotations[user.username]);

    if (historyRoundFilter !== "all") {
      result = result.filter((t: Tweet) => (t.round || 1) === historyRoundFilter);
    }

    // Filter by search term
    if (searchTerm) {
      result = result.filter(
        (t: Tweet) => t.text.includes(searchTerm) || t.id.includes(searchTerm)
      );
    }

    // Sort by timestamp
    result.sort((a: Tweet, b: Tweet) => {
      const timeA = a.annotationTimestamps?.[user.username] || 0;
      const timeB = b.annotationTimestamps?.[user.username] || 0;
      return sortOrder === "newest" ? timeB - timeA : timeA - timeB;
    });

    return result;
  }, [myTweets, user.username, historyRoundFilter, searchTerm, sortOrder]);

  // Mistakes tab receives a dedicated backend query, but we keep a defensive
  // frontend filter to ensure card data remains consistent.
  const mistakesTweets = useMemo(() => {
    return tweets.filter((tweet) => {
      const myLabel = tweet.annotations?.[user.username];
      const finalLabel = tweet.finalLabel;
      if (!myLabel) return false;
      if (!finalLabel || finalLabel === "CONFLICT" || finalLabel === LabelOption.Skip) {
        return false;
      }
      if (mistakesRoundFilter !== "all" && (tweet.round || 1) !== mistakesRoundFilter) {
        return false;
      }
      return myLabel !== finalLabel;
    });
  }, [tweets, user.username, mistakesRoundFilter]);

  const currentTweet = unlabeledTweets.length > 0 ? unlabeledTweets[0] : null;

  const progress = useMemo(() => {
    if (myTweets.length === 0) return 0;
    const completedCount = myTweets.filter(
      (t: Tweet) => t.annotations[user.username]
    ).length;
    return Math.round((completedCount / myTweets.length) * 100);
  }, [myTweets.length, myTweets, user.username]);

  const getLabelColor = (label: string) => {
    switch (label) {
      case LabelOption.Jihadist:
        return "bg-red-50 text-red-700 border-red-200 ring-red-200";
      case LabelOption.Quietist:
        return "bg-purple-50 text-purple-700 border-purple-200 ring-purple-200";
      case LabelOption.Neither:
        return "bg-gray-100 text-gray-700 border-gray-200 ring-gray-200";
      case LabelOption.Skip:
        return "bg-yellow-50 text-yellow-700 border-yellow-200 ring-yellow-200";
      default:
        return "bg-white text-gray-700 border-gray-300";
    }
  };

  const initiateLabel = (tweetId: string, label: string) => {
    setPendingLabel({ tweetId, label });
    setSelectedFeatures([]);
    setSkipReason("");
  };

  const toggleFeature = (feature: string) => {
    setSelectedFeatures((prev) =>
      prev.includes(feature)
        ? prev.filter((f) => f !== feature)
        : [...prev, feature]
    );
  };

  const confirmLabel = () => {
    if (!pendingLabel) return;
    const trimmedSkipReason = skipReason.trim();
    const featuresToSave =
      pendingLabel.label === LabelOption.Skip
        ? [trimmedSkipReason]
        : pendingLabel.label === LabelOption.Jihadist
          ? selectedFeatures
          : [];
    onLabelTweet(pendingLabel.tweetId, pendingLabel.label, featuresToSave);
    setPendingLabel(null);
    setSelectedFeatures([]);
    setSkipReason("");
  };

  const cancelLabel = () => {
    setPendingLabel(null);
    setSelectedFeatures([]);
    setSkipReason("");
  };

  // --- Render ---

  if (myTweets.length === 0 && activeTab === "label") {
    return (
      <div className="max-w-4xl mx-auto p-6 text-center mt-10">
        <div className="bg-white p-10 rounded-xl shadow-sm border border-gray-200">
          <div className="bg-gray-100 p-4 rounded-full inline-flex mb-4">
            <CheckCircle className="w-8 h-8 text-gray-500" />
          </div>
          <h2 className="text-xl font-bold text-gray-900">
            אין ציוצים משויכים
          </h2>
          <p className="text-gray-500 mt-2">
            המרצה טרם שייך אליך ציוצים לתיוג. אנא פנה למרצה.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6">
      {/* Modal ... (Same as before) */}
      {pendingLabel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4 animate-fadeIn">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full flex flex-col max-h-[90vh]">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="text-lg font-bold text-gray-900">
                {pendingLabel.label === LabelOption.Jihadist
                  ? "מדוע בחרת בסיווג זה?"
                  : "אישור הסיווג"}
              </h3>
              <button
                onClick={cancelLabel}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-5 overflow-y-auto">
              <div className="mb-4 bg-gray-50 p-3 rounded text-sm text-gray-600">
                סיווג נבחר:{" "}
                <span
                  className={`font-bold px-2 py-0.5 rounded border ${getLabelColor(
                    pendingLabel.label
                  )}`}
                >
                  {pendingLabel.label}
                </span>
              </div>

              {pendingLabel.label === LabelOption.Jihadist && (
                <>
                  <p className="text-sm text-gray-500 mb-3">
                    אנא סמן את המאפיינים שהובילו להחלטה (ניתן לבחור יותר מאחד):
                  </p>
                  <div className="space-y-2">
                    {LABEL_REASONS.map((reason) => (
                      <label
                        key={reason}
                        className="flex items-start gap-3 p-2 border rounded-lg hover:bg-gray-50 cursor-pointer transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={selectedFeatures.includes(reason)}
                          onChange={() => toggleFeature(reason)}
                          className="mt-1 w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                        />
                        <span className="text-sm text-gray-800">{reason}</span>
                      </label>
                    ))}
                  </div>
                </>
              )}
              {pendingLabel.label === LabelOption.Skip && (
                <div className="space-y-2">
                  <label className="text-sm text-gray-600 block">
                    מה הסיבה לדילוג?
                  </label>
                  <textarea
                    value={skipReason}
                    onChange={(e) => setSkipReason(e.target.value)}
                    placeholder="כתוב/כתבי כאן את הסיבה לדילוג..."
                    rows={4}
                    className="w-full rounded-lg border border-gray-300 p-3 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-yellow-300 focus:border-yellow-400"
                  />
                </div>
              )}
              {pendingLabel.label !== LabelOption.Jihadist &&
                pendingLabel.label !== LabelOption.Skip && (
                <p className="text-sm text-gray-600 text-center py-4">
                  האם אתה בטוח בסיווג זה?
                </p>
                )}
            </div>

            <div className="p-4 border-t border-gray-100 bg-gray-50 rounded-b-xl flex justify-between gap-3">
              <Button
                variant="secondary"
                onClick={cancelLabel}
                className="flex-1"
              >
                ביטול
              </Button>
              <Button
                onClick={confirmLabel}
                disabled={
                  (pendingLabel.label === LabelOption.Jihadist &&
                    selectedFeatures.length === 0) ||
                  (pendingLabel.label === LabelOption.Skip &&
                    skipReason.trim().length === 0)
                }
                className="flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                שמור תיוג
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Header (Same as before) */}
      <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-gray-900">
              שלום, {user.username}
            </h1>
            <p className="text-gray-500">
              {activeTab === "mistakes"
                ? "סקירת ציוצים שבהם ההכרעה הסופית הייתה שונה מהתיוג שלך."
                : "אנא סווג את הציוצים הבאים בהתאם להנחיות."}
            </p>
          </div>
          <div className="flex items-center gap-4 bg-blue-50 px-4 py-2 rounded-lg">
            <div className="text-center">
              <span className="block text-xl font-bold text-blue-700">
                {unlabeledTweets.length}
              </span>
              <span className="text-xs text-blue-600">נותרו</span>
            </div>
            <div className="h-8 w-px bg-blue-200"></div>
            <div className="text-center">
              <span className="block text-xl font-bold text-green-700">
                {myTweets.length - unlabeledTweets.length}
              </span>
              <span className="text-xs text-green-600">הושלמו</span>
            </div>
          </div>
        </div>
        <div className="mt-6">
          <div className="flex justify-between text-sm text-gray-600 mb-1">
            <span>התקדמות כללית</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div
              className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>
      </div>

      <div className="flex border-b border-gray-200 mb-4">
        <button
          onClick={() => onActiveTabChange("label")}
          className={`flex items-center gap-2 px-6 py-3 font-medium text-sm transition-colors border-b-2 ${
            activeTab === "label"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Save className="w-4 h-4" />
          ממשק תיוג
        </button>
        <button
          onClick={() => onActiveTabChange("history")}
          className={`flex items-center gap-2 px-6 py-3 font-medium text-sm transition-colors border-b-2 ${
            activeTab === "history"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <History className="w-4 h-4" />
          היסטוריה ({labeledTweets.length})
        </button>
        <button
          onClick={() => onActiveTabChange("mistakes")}
          className={`flex items-center gap-2 px-6 py-3 font-medium text-sm transition-colors border-b-2 ${
            activeTab === "mistakes"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <AlertTriangle className="w-4 h-4" />
          הטעויות שלי ({mistakesTweets.length})
        </button>
      </div>

      {activeTab === "label" ? (
        <div className="space-y-6">
          {currentTweet ? (
            <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
              <div className="bg-gray-50 px-6 py-4 border-b border-gray-100 flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-500">
                    מזהה ציוץ: {currentTweet.id}
                  </span>
                  <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-1 rounded-full">
                    סבב {currentTweet.round || 1}
                  </span>
                </div>
                <span className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full">
                  ממתין לתיוג
                </span>
              </div>
              <div className="p-8 min-h-fit bg-white">
                <p className="text-lg sm:text-xl leading-relaxed text-gray-800 font-medium whitespace-pre-wrap break-words word-wrap">
                  "{currentTweet.text}"
                </p>
              </div>
              <div className="bg-gray-50 px-6 py-6 border-t border-gray-100">
                <h3 className="text-sm font-semibold text-gray-500 mb-4 uppercase tracking-wider">
                  בחר סיווג:
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <Button
                    onClick={() =>
                      initiateLabel(currentTweet.id, LabelOption.Jihadist)
                    }
                    className="bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 hover:border-red-300 py-3"
                  >
                    {LabelOption.Jihadist}
                  </Button>
                  <Button
                    onClick={() =>
                      initiateLabel(currentTweet.id, LabelOption.Quietist)
                    }
                    className="bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 hover:border-purple-300 py-3"
                  >
                    {LabelOption.Quietist}
                  </Button>
                  <Button
                    onClick={() =>
                      initiateLabel(currentTweet.id, LabelOption.Neither)
                    }
                    className="bg-gray-200 hover:bg-gray-300 text-gray-800 border border-gray-300 hover:border-gray-400 py-3 font-medium"
                  >
                    {LabelOption.Neither}
                  </Button>
                  <Button
                    onClick={() =>
                      initiateLabel(currentTweet.id, LabelOption.Skip)
                    }
                    variant="secondary"
                    className="py-3"
                  >
                    {LabelOption.Skip}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-16 bg-white rounded-lg border border-gray-200 shadow-sm">
              <div className="bg-green-100 p-4 rounded-full inline-flex mb-4">
                <CheckCircle className="w-8 h-8 text-green-600" />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">
                כל הכבוד!
              </h3>
              <p className="text-gray-500">
                סיימת לסווג את כל הציוצים המשויכים אליך.
              </p>
            </div>
          )}
        </div>
      ) : activeTab === "history" ? (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden border border-gray-200">
          <div className="flex flex-col sm:flex-row justify-between items-center px-6 py-4 bg-gray-50 border-b border-gray-200 gap-4">
            <div className="flex items-center gap-4 w-full sm:w-auto flex-1">
              <h3 className="font-medium text-gray-700 whitespace-nowrap">
                היסטוריית תיוגים
              </h3>
              <div className="relative w-full max-w-xs">
                <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
                  <Search className="h-4 w-4 text-gray-400" />
                </div>
                <input
                  type="text"
                  placeholder="חפש בתוכן..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="block w-full pr-10 pl-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:placeholder-gray-400 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                />
              </div>
              <div className="relative">
                <select
                  value={historyRoundFilter}
                  onChange={(e) =>
                    setHistoryRoundFilter(
                      e.target.value === "all" ? "all" : Number(e.target.value),
                    )
                  }
                  className="block w-full pl-3 pr-8 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                >
                  <option value="all">All rounds</option>
                  {availableMyRounds.map((round) => (
                    <option key={round} value={round}>
                      Round {round}
                    </option>
                  ))}
                </select>
              </div>
              <div className="relative">
                <select
                  value={sortOrder}
                  onChange={(e) =>
                    setSortOrder(e.target.value as "newest" | "oldest")
                  }
                  className="block w-full pl-3 pr-8 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md"
                >
                  <option value="newest">הכי חדש</option>
                  <option value="oldest">הכי ישן</option>
                </select>
              </div>
            </div>
            {labeledTweets.length > 0 && (
              <Button
                onClick={() => exportToCSV(myTweets, [user.username])}
                variant="secondary"
                className="text-sm flex items-center gap-2"
              >
                <Download className="w-4 h-4" />
                ייצוא (CSV)
              </Button>
            )}
          </div>

          {labeledTweets.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-20">
                      מזהה
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-20">
                      סבב
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      תוכן הציוץ
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-48">
                      סיווג ונימוקים
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                      פעולות
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {labeledTweets.map((tweet: Tweet) => {
                    const currentLabel = tweet.annotations[user.username];
                    const currentFeatures =
                      tweet.annotationFeatures?.[user.username] || [];
                    const timestamp =
                      tweet.annotationTimestamps?.[user.username];

                    return (
                      <tr key={tweet.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 align-top">
                          <div>{tweet.id}</div>
                          {timestamp && (
                            <div
                              className="text-xs text-gray-400 mt-1 flex items-center gap-1"
                              title={new Date(timestamp).toLocaleString(
                                "he-IL"
                              )}
                            >
                              <Calendar className="w-3 h-3" />
                              {new Date(timestamp).toLocaleDateString("he-IL")}
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 align-top">
                          <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-1 rounded-full">
                            {tweet.round || 1}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-900 max-w-md align-top">
                          <div className="line-clamp-3 hover:line-clamp-none transition-all">
                            {tweet.text}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-sm font-medium align-top">
                          <div
                            className={`inline-block px-2 py-1 rounded text-xs mb-2 ${getLabelColor(
                              currentLabel
                            )}`}
                          >
                            {currentLabel}
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {currentFeatures.map((f: string) => (
                              <span
                                key={f}
                                className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded border border-gray-200"
                              >
                                {f}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 align-top">
                          {/* Allow reset for any past annotation matching current round. */}
                          {(tweet.round || 1) === currentAppRound ? (
                            <Button
                              variant="neutral"
                              onClick={() => onResetLabel(tweet.id)}
                              className="text-xs px-3 py-2 flex items-center gap-1 text-red-600 hover:text-red-700 hover:bg-red-50 w-full justify-center"
                              title="התחרטתי - החזר לתור"
                            >
                              <RotateCcw className="w-4 h-4" /> תיקון
                            </Button>
                          ) : (
                            <span 
                              className="text-xs text-gray-400 flex items-center justify-center pt-2"
                              title={`ניתן לתקן רק סיווגים מהסבב הנוכחי (${currentAppRound})`}
                            >
                              ננעל (סבב {tweet.round || 1})
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500">
              {searchTerm ? (
                <div>
                  <Search className="w-12 h-12 mx-auto mb-2 opacity-20" />
                  <p>לא נמצאו תוצאות עבור "{searchTerm}"</p>
                </div>
              ) : (
                <div>
                  <Clock className="w-12 h-12 mx-auto mb-2 opacity-20" />
                  <p>עדיין לא בוצעו סיווגים</p>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-gray-700 whitespace-nowrap">
                Filter by round
              </span>
              <select
                value={mistakesRoundFilter}
                onChange={(e) =>
                  setMistakesRoundFilter(
                    e.target.value === "all" ? "all" : Number(e.target.value),
                  )
                }
                className="block w-full max-w-xs pl-3 pr-8 py-2 text-sm border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 rounded-md"
              >
                <option value="all">All rounds</option>
                {availableMyRounds.map((round) => (
                  <option key={round} value={round}>
                    Round {round}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {mistakesTweets.length > 0 ? (
            mistakesTweets.map((tweet) => {
              const myLabel = tweet.annotations[user.username];
              return (
                <div
                  key={tweet.id}
                  className="bg-white rounded-xl border border-red-100 shadow-sm p-5"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono bg-gray-100 text-gray-600 px-2 py-1 rounded">
                        #{tweet.id}
                      </span>
                      <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-1 rounded">
                        סבב {tweet.round || 1}
                      </span>
                    </div>
                    <span className="text-xs bg-red-50 text-red-700 border border-red-200 px-2 py-1 rounded">
                      אי התאמה
                    </span>
                  </div>

                  <p className="text-gray-900 leading-relaxed mb-4 whitespace-pre-wrap">
                    "{tweet.text}"
                  </p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                      <p className="text-xs text-gray-500 mb-1">התיוג שלך</p>
                      <p className="text-sm font-semibold text-gray-900">
                        {myLabel || "-"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                      <p className="text-xs text-green-700 mb-1">הכרעת מנהל</p>
                      <p className="text-sm font-semibold text-green-800">
                        {tweet.finalLabel || "-"}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
                    <p className="text-xs text-blue-700 mb-1">סיבת ההכרעה</p>
                    <p className="text-sm text-blue-900">
                      {tweet.resolutionReason?.trim()
                        ? tweet.resolutionReason
                        : "לא הוזנה סיבת הכרעה"}
                    </p>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="text-center py-12 bg-white rounded-lg border border-gray-200 shadow-sm text-gray-500">
              <AlertTriangle className="w-12 h-12 mx-auto mb-2 opacity-20" />
              <p>אין כרגע טעויות להצגה</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
