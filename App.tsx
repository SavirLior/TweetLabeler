import React, { useState, useEffect } from 'react';
import { User, Tweet, UserRole } from './types';
import { getTweets, saveTweet, addTweets, updateTweets, deleteTweet } from './services/dataService';
import { Login } from './components/Login';
import { StudentView } from './components/StudentView';
import { AdminView } from './components/AdminView';
import { LogOut, Database } from 'lucide-react';

const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [tweets, setTweets] = useState<Tweet[]>([]);
  const [isInitialized, setIsInitialized] = useState(false);

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

  const handleLabelTweet = async (tweetId: string, label: string) => {
    if (!currentUser) return;

    // 1. Optimistic Update (Update UI immediately)
    const updatedTweets = tweets.map(tweet => {
      if (tweet.id === tweetId) {
        return {
          ...tweet,
          annotations: {
            ...tweet.annotations,
            [currentUser.username]: label
          },
          annotationTimestamps: {
            ...(tweet.annotationTimestamps || {}),
            [currentUser.username]: Date.now()
          }
        };
      }
      return tweet;
    });
    setTweets(updatedTweets);

    // 2. Persist
    const changedTweet = updatedTweets.find(t => t.id === tweetId);
    if (changedTweet) {
      await saveTweet(changedTweet);
    }
  };

  const handleResetLabel = async (tweetId: string) => {
    if (!currentUser) return;

    // 1. Optimistic Update
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map(tweet => {
      if (tweet.id === tweetId) {
        const newAnnotations = { ...tweet.annotations };
        delete newAnnotations[currentUser.username];
        
        const newTimestamps = { ...(tweet.annotationTimestamps || {}), };
        delete newTimestamps[currentUser.username];
        
        const newTweet = {
          ...tweet,
          annotations: newAnnotations,
          annotationTimestamps: newTimestamps
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

  const handleAdminLabelChange = async (tweetId: string, studentUsername: string, newLabel: string) => {
    // 1. Optimistic
    let changedTweet: Tweet | undefined;
    const updatedTweets = tweets.map(tweet => {
      if (tweet.id === tweetId) {
        const newTweet = {
          ...tweet,
          annotations: {
            ...tweet.annotations,
            [studentUsername]: newLabel
          },
          annotationTimestamps: {
            ...(tweet.annotationTimestamps || {}),
            [studentUsername]: Date.now()
          }
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

  const handleAssignmentChange = async (tweetId: string, assignedTo: string[]) => {
      // 1. Optimistic
      let changedTweet: Tweet | undefined;
      const updatedTweets = tweets.map(tweet => {
          if (tweet.id === tweetId) {
              const newTweet = { ...tweet, assignedTo };
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
      const updatedTweets = tweets.filter(t => t.id !== tweetId);
      setTweets(updatedTweets);

      // 2. Persist
      await deleteTweet(tweetId);
  };

  const handleBulkUpdateTweets = async (updatedList: Tweet[]) => {
      // 1. Optimistic
      // Create a map for faster lookup
      const updatesMap = new Map(updatedList.map(t => [t.id, t]));
      const newTweetsState = tweets.map(t => {
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

  if (!isInitialized) {
    return <div className="min-h-screen flex items-center justify-center">טוען נתונים...</div>;
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
              <span className="text-xl font-bold text-blue-600">TweetLabeler</span>
              <span className="mr-4 px-2 py-1 bg-gray-100 rounded text-xs font-medium text-gray-600">
                גרסת מחקר v1.0
              </span>
            </div>
            <div className="flex items-center gap-4">
              <div title="מסד נתונים מקומי" className="text-gray-600 bg-gray-50 p-1.5 rounded-full flex items-center gap-2 px-3">
                 <Database className="w-4 h-4" />
                 <span className="text-xs font-medium">מקומי</span>
              </div>

              <div className="text-sm text-right hidden sm:block">
                <p className="font-medium text-gray-900">{currentUser.username}</p>
                <p className="text-xs text-gray-500">{currentUser.role === UserRole.Admin ? 'מנהל מערכת' : 'סטודנט'}</p>
              </div>
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
    </div>
  );
};

export default App;