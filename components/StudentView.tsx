import React, { useMemo, useState } from 'react';
import { User, Tweet, LabelOption } from '../types';
import { Button } from './Button';
import { exportToCSV } from '../services/dataService';
import { CheckCircle, Clock, Save, History, RotateCcw, Download, Trash2, Search, ArrowUpDown, Calendar, Lock } from 'lucide-react';

interface StudentViewProps {
  user: User;
  tweets: Tweet[];
  onLabelTweet: (tweetId: string, label: string) => void;
  onResetLabel: (tweetId: string) => void;
}

export const StudentView: React.FC<StudentViewProps> = ({ user, tweets, onLabelTweet, onResetLabel }) => {
  const [activeTab, setActiveTab] = useState<'label' | 'history'>('label');
  const [searchTerm, setSearchTerm] = useState('');
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

  // Filter tweets specifically assigned to this user
  const myTweets = useMemo(() => {
    return tweets.filter(t => t.assignedTo?.includes(user.username));
  }, [tweets, user.username]);

  // Tweets that have NOT been labeled by this user
  const unlabeledTweets = useMemo(() => {
    return myTweets.filter(t => !t.annotations[user.username]);
  }, [myTweets, user.username]);

  // Tweets that HAVE been labeled by this user, filtered and sorted
  const labeledTweets = useMemo(() => {
    let result = myTweets.filter(t => t.annotations[user.username]);

    // Filter by search term
    if (searchTerm) {
      result = result.filter(t => 
        t.text.includes(searchTerm) || t.id.includes(searchTerm)
      );
    }

    // Sort by timestamp
    result.sort((a, b) => {
      const timeA = a.annotationTimestamps?.[user.username] || 0;
      const timeB = b.annotationTimestamps?.[user.username] || 0;
      return sortOrder === 'newest' ? timeB - timeA : timeA - timeB;
    });

    return result;
  }, [myTweets, user.username, searchTerm, sortOrder]);

  const currentTweet = unlabeledTweets.length > 0 ? unlabeledTweets[0] : null;

  const progress = useMemo(() => {
    if (myTweets.length === 0) return 0;
    const completedCount = myTweets.filter(t => t.annotations[user.username]).length;
    return Math.round((completedCount / myTweets.length) * 100);
  }, [myTweets.length, myTweets, user.username]);

  const getLabelColor = (label: string) => {
    switch (label) {
        case LabelOption.Jihadist: return "bg-red-50 text-red-700 border-red-200 ring-red-200";
        case LabelOption.Quietist: return "bg-purple-50 text-purple-700 border-purple-200 ring-purple-200";
        case LabelOption.Neither: return "bg-gray-100 text-gray-700 border-gray-200 ring-gray-200";
        case LabelOption.Skip: return "bg-yellow-50 text-yellow-700 border-yellow-200 ring-yellow-200";
        default: return "bg-white text-gray-700 border-gray-300";
    }
  };

  if (myTweets.length === 0 && activeTab === 'label') {
    return (
      <div className="max-w-4xl mx-auto p-6 text-center mt-10">
        <div className="bg-white p-10 rounded-xl shadow-sm border border-gray-200">
           <div className="bg-gray-100 p-4 rounded-full inline-flex mb-4">
              <Lock className="w-8 h-8 text-gray-500" />
           </div>
           <h2 className="text-xl font-bold text-gray-900">אין ציוצים משויכים</h2>
           <p className="text-gray-500 mt-2">המרצה טרם שייך אליך ציוצים לתיוג. אנא פנה למרצה.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6">
      {/* Header & Stats */}
      <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
        <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">שלום, {user.username}</h1>
            <p className="text-gray-500">אנא סווג את הציוצים הבאים בהתאם להנחיות.</p>
          </div>
          <div className="flex items-center gap-4 bg-blue-50 px-4 py-2 rounded-lg">
            <div className="text-center">
              <span className="block text-xl font-bold text-blue-700">{unlabeledTweets.length}</span>
              <span className="text-xs text-blue-600">נותרו</span>
            </div>
            <div className="h-8 w-px bg-blue-200"></div>
            <div className="text-center">
              <span className="block text-xl font-bold text-green-700">{myTweets.length - unlabeledTweets.length}</span>
              <span className="text-xs text-green-600">הושלמו</span>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
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

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-4">
        <button
          onClick={() => setActiveTab('label')}
          className={`flex items-center gap-2 px-6 py-3 font-medium text-sm transition-colors border-b-2 ${
            activeTab === 'label' 
              ? 'border-blue-600 text-blue-600' 
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <Save className="w-4 h-4" />
          ממשק תיוג
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`flex items-center gap-2 px-6 py-3 font-medium text-sm transition-colors border-b-2 ${
            activeTab === 'history' 
              ? 'border-blue-600 text-blue-600' 
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <History className="w-4 h-4" />
          היסטוריה ({labeledTweets.length})
        </button>
      </div>

      {/* Content Area */}
      {activeTab === 'label' ? (
        <div className="space-y-6">
          {currentTweet ? (
            <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
              <div className="bg-gray-50 px-6 py-4 border-b border-gray-100 flex justify-between items-center">
                <span className="text-sm font-medium text-gray-500">מזהה ציוץ: {currentTweet.id}</span>
                <span className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full">ממתין לתיוג</span>
              </div>
              
              <div className="p-8">
                <p className="text-xl sm:text-2xl leading-relaxed text-gray-800 font-medium">
                  "{currentTweet.text}"
                </p>
              </div>

              <div className="bg-gray-50 px-6 py-6 border-t border-gray-100">
                <h3 className="text-sm font-semibold text-gray-500 mb-4 uppercase tracking-wider">בחר סיווג:</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <Button 
                    onClick={() => onLabelTweet(currentTweet.id, LabelOption.Jihadist)}
                    className="bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 hover:border-red-300 py-3"
                  >
                    {LabelOption.Jihadist}
                  </Button>
                  <Button 
                    onClick={() => onLabelTweet(currentTweet.id, LabelOption.Quietist)}
                    className="bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 hover:border-purple-300 py-3"
                  >
                    {LabelOption.Quietist}
                  </Button>
                  <Button 
                    onClick={() => onLabelTweet(currentTweet.id, LabelOption.Neither)}
                    className="bg-gray-200 hover:bg-gray-300 text-gray-800 border border-gray-300 hover:border-gray-400 py-3 font-medium"
                  >
                    {LabelOption.Neither}
                  </Button>
                  <Button 
                    onClick={() => onLabelTweet(currentTweet.id, LabelOption.Skip)}
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
              <h3 className="text-xl font-bold text-gray-900 mb-2">כל הכבוד!</h3>
              <p className="text-gray-500">סיימת לסווג את כל הציוצים המשויכים אליך.</p>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden border border-gray-200">
          <div className="flex flex-col sm:flex-row justify-between items-center px-6 py-4 bg-gray-50 border-b border-gray-200 gap-4">
             <div className="flex items-center gap-4 w-full sm:w-auto flex-1">
                <h3 className="font-medium text-gray-700 whitespace-nowrap">היסטוריית תיוגים</h3>
                
                {/* Search Bar */}
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

                {/* Sort Filter */}
                <div className="relative">
                   <select
                      value={sortOrder}
                      onChange={(e) => setSortOrder(e.target.value as 'newest' | 'oldest')}
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
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-20">מזהה</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">תוכן הציוץ</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-48">סיווג</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-24">פעולות</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {labeledTweets.map((tweet) => {
                    const currentLabel = tweet.annotations[user.username];
                    const timestamp = tweet.annotationTimestamps?.[user.username];
                    
                    return (
                      <tr key={tweet.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 align-top">
                          <div>{tweet.id}</div>
                          {timestamp && (
                             <div className="text-xs text-gray-400 mt-1 flex items-center gap-1" title={new Date(timestamp).toLocaleString('he-IL')}>
                               <Calendar className="w-3 h-3" />
                               {new Date(timestamp).toLocaleDateString('he-IL')}
                             </div>
                          )}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-900 max-w-md align-top">
                          <div className="line-clamp-3 hover:line-clamp-none transition-all">{tweet.text}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium align-top">
                          <select
                            value={currentLabel}
                            onChange={(e) => onLabelTweet(tweet.id, e.target.value)}
                            className={`block w-full py-1.5 px-3 text-sm border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-500 ${getLabelColor(currentLabel)}`}
                          >
                            {Object.values(LabelOption).map((option) => (
                              <option key={option} value={option} className="bg-white text-gray-900">{option}</option>
                            ))}
                          </select>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 align-top">
                           <Button 
                              variant="neutral" 
                              onClick={() => onResetLabel(tweet.id)}
                              className="text-xs px-3 py-2 flex items-center gap-1 text-red-600 hover:text-red-700 hover:bg-red-50 w-full justify-center"
                              title="החזר לתור (מחק תיוג)"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
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
      )}
    </div>
  );
};