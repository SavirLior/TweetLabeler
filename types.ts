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

export interface Tweet {
  id: string;
  text: string;
  // List of usernames who are assigned to label this tweet
  assignedTo?: string[];
  // Map username to the annotation they chose
  annotations: Record<string, string>;
  // Map username to the timestamp of when they annotated
  annotationTimestamps?: Record<string, number>;
}

export interface AppData {
  tweets: Tweet[];
  users?: User[];
}