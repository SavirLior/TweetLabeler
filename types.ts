export enum UserRole {
  Student = 'student',
  Admin = 'admin'
}

export interface User {
  username: string;
  password?: string;
  role: UserRole;
}

export enum LabelOption {
  Jihadist = "סלפי ג'יהאדיסטי",
  Quietist = "סלפי תקלידי",
  Neither = "לא זה ולא זה",
  Skip = "לא בטוח / דלג"
}

export const LABEL_REASONS = [
  "א. האשמה בכפירה של שליטי ערב",
  "ב. ביטויי גנאי או האשמה בכפירה של חכמי הלכה",
  "ג. קריאה לג׳האד התקפי (לא הגנתי)",
  "ד. תמיכה בתכפיר קולקטיבי",
  "ה. ביקורת על סלפים מקלידים",
  "ו. תמיכה או ציטוט של דמויות סלפיות ג׳האדיות מוכרות",
  "ז. אחר"
];


export interface Tweet {
  id: string;
  text: string;
  // List of usernames who are assigned to label this tweet
  assignedTo?: string[];
  // Map username to the annotation they chose
  annotations: Record<string, string>;
  // Map username to the features/reasons they selected
  annotationFeatures?: Record<string, string[]>;
  // Map username to the timestamp of when they annotated
  annotationTimestamps?: Record<string, number>;
  
  // The final resolved label (Automatic consensus or Admin override)
  finalLabel?: string; 
}

export interface AppData {
  tweets: Tweet[];
  users?: User[];
}