import { Tweet, AppData, User, UserRole } from '../types';

const API_URL = 'http://localhost:5000/api';

// --- Helper for fetch with error handling ---
const apiRequest = async (endpoint: string, method: string = 'GET', body?: any) => {
    try {
        const options: RequestInit = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(`${API_URL}${endpoint}`, options);
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`Failed to request ${endpoint}:`, error);
        throw error;
    }
};

// --- Data Fetching ---

export const getTweets = async (): Promise<Tweet[]> => {
    try {
        const data = await apiRequest('/data');
        return data.tweets || [];
    } catch (e) {
        console.error("Could not connect to backend, ensure server.py is running.");
        // Fallback for UI if server is down, though it won't persist
        return [];
    }
};

// --- Data Saving ---

export const saveTweet = async (tweet: Tweet): Promise<void> => {
    await apiRequest('/tweet', 'POST', tweet);
};

export const updateTweets = async (updatedTweetsList: Tweet[]): Promise<void> => {
    await apiRequest('/tweets/bulk', 'POST', updatedTweetsList);
};

export const addTweets = async (newTweets: Tweet[]): Promise<void> => {
    await apiRequest('/tweets/add', 'POST', newTweets);
};

export const deleteTweet = async (tweetId: string): Promise<void> => {
    await apiRequest(`/tweet/${tweetId}`, 'DELETE');
};

// --- User Management ---

export const getUsers = async (): Promise<User[]> => {
    try {
        const data = await apiRequest('/data');
        return data.users || [];
    } catch (e) {
        return [];
    }
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
    try {
        return await apiRequest('/users/register', 'POST', user);
    } catch (e) {
        throw new Error('שם המשתמש כבר קיים או שיש בעיית תקשורת');
    }
};

// --- Export ---

export const exportToCSV = (tweets: Tweet[], users: string[]) => {
  // Build header: ID, Text, AssignedTo, Final Decision, then for each user [Label, Features]
  const header = ['Tweet ID', 'Text', 'Final Decision', 'Assigned To'];
  users.forEach(u => {
      header.push(`Label_${u}`);
      header.push(`Reasons_${u}`);
  });
  
  const rows = tweets.map(tweet => {
    const assignedStr = tweet.assignedTo ? tweet.assignedTo.join(';') : '';
    const finalLabel = tweet.finalLabel === 'CONFLICT' ? 'CONFLICT (Unresolved)' : (tweet.finalLabel || '');
    
    const row = [
      tweet.id,
      `"${tweet.text.replace(/"/g, '""')}"`,
      `"${finalLabel}"`,
      `"${assignedStr}"`
    ];

    users.forEach(u => {
        const label = tweet.annotations[u] || '';
        const features = tweet.annotationFeatures?.[u]?.join('; ') || '';
        row.push(`"${label}"`);
        row.push(`"${features}"`);
    });

    return row.join(',');
  });

  const csvContent = "\uFEFF" + [header.join(','), ...rows].join('\n'); 
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', `tweets_labels_detailed_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};