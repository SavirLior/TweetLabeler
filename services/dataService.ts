import { Tweet, AppData, User, UserRole } from '../types';

const STORAGE_KEY = 'tweet_labeler_data';
const USERS_STORAGE_KEY = 'tweet_labeler_users';

const DUMMY_TWEETS: Tweet[] = [
  {
    id: '1',
    text: 'חובה עלינו לחזור למקורות ולטהר את האמונה מכל חידוש פסול. רק כך נצליח לכונן חברה צודקת.',
    assignedTo: ['student1'],
    annotations: {}
  },
  {
    id: '2',
    text: 'המנהיגים הנוכחיים הם כופרים ויש להילחם בהם בכל האמצעים האפשריים עד להפלתם.',
    assignedTo: ['student1', 'student2'],
    annotations: {}
  },
  {
    id: '3',
    text: 'עדיף לסבול שליט עריץ מאשר ליצור כאוס במדינה. עלינו להתמקד בלימוד תורה וחינוך.',
    assignedTo: ['student2'],
    annotations: {}
  },
  {
    id: '4',
    text: 'היום הלכתי לקניון וקניתי נעליים חדשות, היה מבצע ממש שווה.',
    assignedTo: ['student1'],
    annotations: {}
  },
  {
    id: '5',
    text: 'הג\'יהאד הוא הדרך היחידה להחזיר את כבוד האומה האסלאמית.',
    assignedTo: ['student1', 'student2'],
    annotations: {}
  }
];

const DEFAULT_USERS: User[] = [
  { username: 'admin', password: '123', role: UserRole.Admin },
  { username: 'student1', password: '123', role: UserRole.Student },
  { username: 'student2', password: '123', role: UserRole.Student },
];

// --- Data Fetching ---

export const getTweets = async (): Promise<Tweet[]> => {
  // Simulate DB Delay for realism (optional, but good for UX)
  // await new Promise(resolve => setTimeout(resolve, 300));

  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try {
      const parsed: AppData = JSON.parse(stored);
      if (Array.isArray(parsed.tweets)) {
        return parsed.tweets;
      }
    } catch (e) {
      console.error("Failed to parse stored data", e);
    }
  }
  
  const initialData: AppData = { tweets: DUMMY_TWEETS };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(initialData));
  return DUMMY_TWEETS;
};

// --- Data Saving ---

export const saveTweet = async (tweet: Tweet): Promise<void> => {
  const tweets = await getTweets();
  const updatedTweets = tweets.map(t => t.id === tweet.id ? tweet : t);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ tweets: updatedTweets }));
};

export const updateTweets = async (updatedTweetsList: Tweet[]): Promise<void> => {
    const currentTweets = await getTweets();
    // Create a map for faster lookup
    const updatesMap = new Map(updatedTweetsList.map(t => [t.id, t]));
    
    const newTweetsState = currentTweets.map(t => {
        return updatesMap.has(t.id) ? updatesMap.get(t.id)! : t;
    });

    localStorage.setItem(STORAGE_KEY, JSON.stringify({ tweets: newTweetsState }));
};

export const addTweets = async (newTweets: Tweet[]): Promise<void> => {
  const tweets = await getTweets();
  const combined = [...tweets, ...newTweets];
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ tweets: combined }));
};

export const deleteTweet = async (tweetId: string): Promise<void> => {
  const tweets = await getTweets();
  const filteredTweets = tweets.filter(t => t.id !== tweetId);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ tweets: filteredTweets }));
};

// --- User Management ---

export const getUsers = async (): Promise<User[]> => {
  const stored = localStorage.getItem(USERS_STORAGE_KEY);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch (e) {
      console.error("Failed to parse users", e);
    }
  }
  
  // Initialize default if empty
  localStorage.setItem(USERS_STORAGE_KEY, JSON.stringify(DEFAULT_USERS));
  return DEFAULT_USERS;
};

export const getAllStudents = async (): Promise<string[]> => {
    const users = await getUsers();
    return users.filter(u => u.role === UserRole.Student).map(u => u.username);
};

export const authenticateUser = async (username: string, password: string): Promise<User | null> => {
  const users = await getUsers();
  const user = users.find(u => u.username === username && u.password === password);
  return user || null;
};

export const registerUser = async (user: User): Promise<User> => {
  const users = await getUsers();
  if (users.some(u => u.username === user.username)) {
    throw new Error('שם המשתמש כבר קיים במערכת');
  }
  
  const updatedUsers = [...users, user];
  localStorage.setItem(USERS_STORAGE_KEY, JSON.stringify(updatedUsers));
  return user;
};

// --- Export ---

export const exportToCSV = (tweets: Tweet[], users: string[]) => {
  const header = ['Tweet ID', 'Text', 'Assigned To', ...users.map(u => `Label_${u}`)];
  
  const rows = tweets.map(tweet => {
    const assignedStr = tweet.assignedTo ? tweet.assignedTo.join(';') : '';
    const row = [
      tweet.id,
      `"${tweet.text.replace(/"/g, '""')}"`,
      `"${assignedStr}"`,
      ...users.map(u => {
        const label = tweet.annotations[u] || '';
        return `"${label}"`;
      })
    ];
    return row.join(',');
  });

  const csvContent = "\uFEFF" + [header.join(','), ...rows].join('\n'); 
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', `tweets_labels_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};