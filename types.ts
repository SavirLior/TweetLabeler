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
  "ציטוט מהקוראן / חדית'",
  "קריאה לתכפיר (הכרזה על כפירה)",
  "קריאה לג'יהאד / אלימות",
  "תמיכה בארגון/מנהיג סלפי",
  "שימוש במונחים סלפיים מובהקים (וולא וברא, תוחיד וכו')",
  "ביקורת פוליטית על שליטים (ח'רוג')",
  "קריאה לציות לשליט (ולי אל-אמר)",
  "נושא כללי / לא רלוונטי",
  "אחר"
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