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
  Jihadist = "Salafi jihadi",
  Quietist = "Salafi taklidi",
  Neither = "Irrelevant",
  Skip = "Skip"
}

export const LABEL_REASONS = [
  "א. האשמה בכפירה של שליטי ערב",
  "ב. ביטויי גנאי או האשמה בכפירה של חכמי הלכה",
  "ג. קריאה לג׳האד התקפי (לא הגנתי)",
  "ד. תמיכה בתכפיר קולקטיבי",
  "ביקורת על סלאפים תקלידיים",
  "ו. תמיכה או ציטוט של דמויות סלפיות ג׳האדיות מוכרות",
"ו. תמיכה בארגוני טרור",
  "ח. אחר"
  
];


export interface Tweet {
  _id?: string;
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
  // Optional admin explanation for how a conflict was resolved.
  resolutionReason?: string;
  // Conflict history state (persists until admin removes from resolved conflicts view)
  wasInConflict?: boolean;
  conflictHistoryDismissed?: boolean;
  conflictDetectedAt?: number;
  conflictResolvedAt?: number;
  v?: number;
}

export interface AppData {
  tweets: Tweet[];
  users?: User[];
}
