import { Tweet, AppData, User, UserRole } from "../types";

const API_URL = "/api";

// --- Helper for fetch with error handling and timeout ---
const apiRequest = async (
  endpoint: string,
  method: string = "GET",
  body?: any
) => {
  // Create a controller to handle the 5-second timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  try {
    const options: RequestInit = {
      method,
      headers: { "Content-Type": "application/json" },
      signal: controller.signal, // Pass the abort signal to fetch
    };
    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_URL}${endpoint}`, options);
    
    // Clear the timer if the request succeeded before 5 seconds
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }
    return await response.json();
  } catch (error: any) {
    // Clear the timer on error to prevent memory leaks
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      console.error(`Request to ${endpoint} timed out after 5 seconds.`);
      throw new Error("Server took too long to respond");
    }
    
    console.error(`Failed to request ${endpoint}:`, error);
    throw error;
  }
};

// --- Data Fetching ---

export const getTweets = async (): Promise<Tweet[]> => {
  try {
    const data = await apiRequest("/data");
    return data.tweets || [];
  } catch (error) {
    console.error("Could not connect to backend, ensure server.py is running.");
    // Throw the error so App.tsx knows the initial load failed and can lock the UI
    throw error;
  }
};

// --- Data Saving ---

export const saveTweet = async (tweet: Tweet): Promise<void> => {
  await apiRequest("/tweet", "POST", tweet);
};

export const updateTweets = async (
  updatedTweetsList: Tweet[]
): Promise<void> => {
  await apiRequest("/tweets/bulk", "POST", updatedTweetsList);
};

export const addTweets = async (newTweets: Tweet[]): Promise<void> => {
  await apiRequest("/tweets/add", "POST", newTweets);
};

export const deleteTweet = async (tweetId: string): Promise<void> => {
  await apiRequest(`/tweet/${tweetId}`, "DELETE");
};

// --- User Management ---

export const getUsers = async (): Promise<User[]> => {
  try {
    const data = await apiRequest("/data");
    return data.users || [];
  } catch (error) {
    // Throw error to prevent silent failures
    throw error;
  }
};

export const getAllStudents = async (): Promise<string[]> => {
  const users = await getUsers();
  return users
    .filter((u) => u.role === UserRole.Student)
    .map((u) => u.username);
};

export const authenticateUser = async (
  username: string,
  password: string
): Promise<User | null> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(`${API_URL}/users/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);

    if (response.status === 401 || response.status === 404) {
      // Return null for invalid credentials
      return null;
    }
    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }
    return await response.json();
  } catch (error: any) {
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      console.error("Authentication timed out after 5 seconds.");
      throw new Error("Server took too long to respond");
    }
    
    console.error("Failed to authenticate user:", error);
    throw error;
  }
};

export const registerUser = async (user: User): Promise<User> => {
  try {
    return await apiRequest("/users/register", "POST", user);
  } catch (error) {
    throw new Error("שם המשתמש כבר קיים או שיש בעיית תקשורת");
  }
};

export const changePassword = async (
  username: string,
  currentPassword: string,
  newPassword: string
): Promise<{ success: boolean; message?: string; error?: string }> => {
  try {
    return await apiRequest("/users/change-password", "POST", {
      username,
      currentPassword,
      newPassword,
    });
  } catch (error) {
    throw new Error("שגיאה בשינוי הסיסמה");
  }
};

// --- Export ---

export const exportToCSV = (tweets: Tweet[], users: string[]) => {
  // Build header: ID, Text, AssignedTo, Final Decision, then for each user [Label, Features]
  const header = ["Tweet ID", "Text", "Final Decision", "Assigned To"];
  users.forEach((u) => {
    header.push(`Label_${u}`);
    header.push(`Reasons_${u}`);
  });

  const rows = tweets.map((tweet) => {
    const assignedStr = tweet.assignedTo ? tweet.assignedTo.join(";") : "";
    const finalLabel =
      tweet.finalLabel === "CONFLICT"
        ? "CONFLICT (Unresolved)"
        : tweet.finalLabel || "";

    const row = [
      tweet.id,
      `"${tweet.text.replace(/"/g, '""')}"`,
      `"${finalLabel}"`,
      `"${assignedStr}"`,
    ];

    users.forEach((u) => {
      const label = tweet.annotations[u] || "";
      const features = tweet.annotationFeatures?.[u]?.join("; ") || "";
      row.push(`"${label}"`);
      row.push(`"${features}"`);
    });

    return row.join(",");
  });

  const csvContent = "\uFEFF" + [header.join(","), ...rows].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute(
    "download",
    `tweets_labels_detailed_${new Date().toISOString().slice(0, 10)}.csv`
  );
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export const saveAnnotation = async (
  tweetId: string, 
  username: string, 
  label: string, 
  features: string[],
  finalLabel?: string 
): Promise<void> => {
    const payload = {
        tweetId,
        username,
        label,
        features,
        timestamp: Date.now(),
        finalLabel
    };
    
    await apiRequest('/tweet/annotate', 'POST', payload);
};