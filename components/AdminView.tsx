import React, { useMemo, useState, useEffect, useRef } from 'react';
import { Tweet, LabelOption } from '../types';
import { Button } from './Button';
import { exportToCSV, getAllStudents } from '../services/dataService';
import { Download, Users, FileText, CheckSquare, BarChart2, Edit3, Filter, Upload, Plus, AlertCircle, RefreshCw, X, Trash2, FileSpreadsheet, AlertTriangle, Shuffle, Play, Settings, Eye, Maximize2, Info, HelpCircle } from 'lucide-react';

interface AdminViewProps {
  tweets: Tweet[];
  onAdminLabelChange: (tweetId: string, studentUsername: string, newLabel: string) => void;
  onAddTweets: (newTweets: Tweet[]) => void;
  onBulkUpdateTweets: (tweets: Tweet[]) => void;
  onDeleteTweet: (tweetId: string) => void;
  onUpdateAssignment: (tweetId: string, assignedTo: string[]) => void;
}

// Local interface for the drafting stage
interface DraftTweet {
  tempId: string;
  text: string;
  assignedTo: string[];
}

// Interface for Auto Assignment Config
interface AssignmentConfig {
    selectedStudents: string[];
    overlapPercentage: number;
}

export const AdminView: React.FC<AdminViewProps> = ({ tweets, onAdminLabelChange, onAddTweets, onBulkUpdateTweets, onDeleteTweet, onUpdateAssignment }) => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'upload'>('dashboard');
  
  // Filters
  const [selectedStudentFilter, setSelectedStudentFilter] = useState<string>('all');
  const [selectedLabelFilter, setSelectedLabelFilter] = useState<string>('all');
  const [showConflictsOnly, setShowConflictsOnly] = useState(false);
  
  // Available students list
  const [availableStudents, setAvailableStudents] = useState<string[]>([]);

  // --- Upload / Draft State ---
  const [draftTweets, setDraftTweets] = useState<DraftTweet[]>([]);
  const [pasteText, setPasteText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // --- Auto Assign State ---
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [assignmentConfig, setAssignmentConfig] = useState<AssignmentConfig>({
      selectedStudents: [],
      overlapPercentage: 20
  });

  // --- Edit Detail Modal State ---
  const [editingTweet, setEditingTweet] = useState<Tweet | null>(null);

  useEffect(() => {
    // Fetch students list on mount or when tab changes to refresh list
    const loadStudents = async () => {
        const students = await getAllStudents();
        setAvailableStudents(students);
        // Default assignment config to all students
        setAssignmentConfig(prev => ({ ...prev, selectedStudents: students }));
    };
    loadStudents();
  }, [activeTab, showAssignModal]); // Reload when modal opens too

  // --- Statistics Logic ---
  const { studentStats, allStudentNames } = useMemo(() => {
    const stats: Record<string, number> = {};
    const students = new Set<string>();

    tweets.forEach(tweet => {
      // Count existing labels
      Object.keys(tweet.annotations).forEach(username => {
        students.add(username);
        stats[username] = (stats[username] || 0) + 1;
      });
    });

    // Also include students from dynamic list
    availableStudents.forEach(s => students.add(s));
    
    const studentList = Array.from(students).sort();

    return {
      allStudentNames: studentList,
      studentStats: studentList.map(student => {
        const totalAssigned = tweets.filter(t => t.assignedTo?.includes(student)).length;
        return {
            name: student,
            labeledCount: stats[student] || 0,
            totalAssigned: totalAssigned
        };
      })
    };
  }, [tweets, availableStudents]);

  const handleExport = () => {
    const allUsers = studentStats.map(s => s.name);
    exportToCSV(tweets, allUsers);
  };

  const handleDeleteClick = (tweetId: string) => {
      if (window.confirm('האם אתה בטוח שברצונך למחוק ציוץ זה לצמיתות?')) {
          onDeleteTweet(tweetId);
          if (editingTweet?.id === tweetId) {
              setEditingTweet(null);
          }
      }
  };

  const handleToggleAssignment = (student: string) => {
      if (!editingTweet) return;
      
      const currentAssigned = editingTweet.assignedTo || [];
      let newAssigned: string[];
      
      if (currentAssigned.includes(student)) {
          newAssigned = currentAssigned.filter(s => s !== student);
      } else {
          newAssigned = [...currentAssigned, student];
      }

      onUpdateAssignment(editingTweet.id, newAssigned);
      
      // Update local state for immediate UI feedback in modal
      setEditingTweet({
          ...editingTweet,
          assignedTo: newAssigned
      });
  };

  // --- Helper: Conflict Detection ---
  const hasConflict = (tweet: Tweet) => {
      const labels = Object.values(tweet.annotations).filter(Boolean); // Get all labels given
      if (labels.length < 2) return false;
      
      const uniqueLabels = new Set(labels);
      // Remove 'Skip' if you want to be lenient, but usually skip is a valid label to conflict with
      return uniqueLabels.size > 1;
  };

  // --- Helper: Filtering Logic ---
  const filteredTweets = useMemo(() => {
      return tweets.filter(tweet => {
          // 1. Conflict Filter
          if (showConflictsOnly && !hasConflict(tweet)) return false;

          // 2. Label Filter (Show tweet if ANY student gave it this label)
          if (selectedLabelFilter !== 'all') {
             const labels = Object.values(tweet.annotations);
             if (!labels.includes(selectedLabelFilter)) return false;
          }

          // 3. Note: Student filter is handled in render column visibility, 
          // but we could also filter rows if the student hasn't touched it. 
          // For now, keeping rows visible but filtering columns is better for admin view.
          
          return true;
      });
  }, [tweets, showConflictsOnly, selectedLabelFilter]);

  // --- Draft / Upload Logic ---

  const handleTextToDraft = () => {
    if (!pasteText.trim()) return;
    
    const lines = pasteText.split('\n').filter(line => line.trim().length > 0);
    const newDrafts: DraftTweet[] = lines.map(line => ({
      tempId: Math.random().toString(36).substr(2, 9),
      text: line.trim(),
      assignedTo: [] // Start with no assignment
    }));

    setDraftTweets(prev => [...prev, ...newDrafts]);
    setPasteText('');
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (content) {
        // Simple CSV parsing: split by line, remove quotes if they wrap the entire line
        const lines = content.split(/\r?\n/).filter(line => line.trim().length > 0);
        
        const newDrafts: DraftTweet[] = lines.map(line => {
          let text = line.trim();
          // Remove surrounding quotes if present (basic CSV handling)
          if (text.startsWith('"') && text.endsWith('"')) {
            text = text.slice(1, -1).replace(/""/g, '"');
          }
          return {
             tempId: Math.random().toString(36).substr(2, 9),
             text: text,
             assignedTo: []
          };
        }).filter(d => d.text.toLowerCase() !== 'text' && d.text.toLowerCase() !== 'tweet');

        setDraftTweets(prev => [...prev, ...newDrafts]);
      }
    };
    reader.readAsText(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeDraft = (tempId: string) => {
    setDraftTweets(prev => prev.filter(t => t.tempId !== tempId));
  };

  const clearAllDrafts = () => {
    if (window.confirm('האם אתה בטוח שברצונך לנקות את כל הטיוטות?')) {
      setDraftTweets([]);
    }
  };

  const toggleDraftAssignment = (tempId: string, student: string) => {
    setDraftTweets(prev => prev.map(t => {
      if (t.tempId !== tempId) return t;
      const current = t.assignedTo || [];
      const updated = current.includes(student) 
        ? current.filter(s => s !== student)
        : [...current, student];
      return { ...t, assignedTo: updated };
    }));
  };

  const bulkAssignDrafts = (student: string) => {
    setDraftTweets(prev => prev.map(t => {
      const current = t.assignedTo || [];
      if (!current.includes(student)) {
        return { ...t, assignedTo: [...current, student] };
      }
      return t;
    }));
  };

  const saveDraftsToSystem = () => {
    if (draftTweets.length === 0) return;

    const newTweets: Tweet[] = draftTweets.map(draft => ({
      id: Math.random().toString(36).substr(2, 9),
      text: draft.text,
      annotations: {},
      assignedTo: draft.assignedTo.length > 0 ? draft.assignedTo : undefined
    }));

    onAddTweets(newTweets);
    setDraftTweets([]);
    alert(`${newTweets.length} ציוצים נוספו למערכת בהצלחה!`);
  };

  // --- Auto Assignment Logic ---

  const handleAutoAssign = () => {
      const { selectedStudents, overlapPercentage } = assignmentConfig;
      if (selectedStudents.length === 0) {
          alert('אנא בחר לפחות סטודנט אחד.');
          return;
      }

      // 1. Identify unassigned tweets
      const unassignedTweets = tweets.filter(t => !t.assignedTo || t.assignedTo.length === 0);
      
      if (unassignedTweets.length === 0) {
          alert('לא נמצאו ציוצים ללא שיוך.');
          setShowAssignModal(false);
          return;
      }

      // 2. Determine number of tweets to have overlap
      const totalTweets = unassignedTweets.length;
      const overlapCount = Math.floor(totalTweets * (overlapPercentage / 100));
      
      // 3. Shuffle tweets
      const shuffledTweets = [...unassignedTweets].sort(() => Math.random() - 0.5);
      
      // 4. Distribute
      const tweetsToUpdate: Tweet[] = [];
      
      // Helper to get next student index round-robin
      let studentIdx = 0;
      const getNextStudent = () => {
          const s = selectedStudents[studentIdx];
          studentIdx = (studentIdx + 1) % selectedStudents.length;
          return s;
      };

      shuffledTweets.forEach((tweet, index) => {
          const newAssigned: string[] = [];
          
          // First assignment (everyone gets one)
          newAssigned.push(getNextStudent());

          // Overlap assignment (for the first X tweets)
          if (index < overlapCount && selectedStudents.length > 1) {
              let secondStudent = getNextStudent();
              // Ensure different student
              while (secondStudent === newAssigned[0]) {
                  secondStudent = getNextStudent();
              }
              newAssigned.push(secondStudent);
          }
          
          tweetsToUpdate.push({
              ...tweet,
              assignedTo: newAssigned
          });
      });

      onBulkUpdateTweets(tweetsToUpdate);
      setShowAssignModal(false);
      alert(`${tweetsToUpdate.length} ציוצים שויכו בהצלחה.`);
  };


  // --- Render Helpers ---

  const getLabelColor = (label: string | undefined) => {
    if (!label) return "bg-gray-50 text-gray-400 border-gray-300";
    switch (label) {
        case LabelOption.Jihadist: return "bg-red-50 text-red-700 border-red-200 ring-red-200 font-medium";
        case LabelOption.Quietist: return "bg-purple-50 text-purple-700 border-purple-200 ring-purple-200 font-medium";
        case LabelOption.Neither: return "bg-gray-100 text-gray-700 border-gray-200 ring-gray-200 font-medium";
        case LabelOption.Skip: return "bg-yellow-50 text-yellow-700 border-yellow-200 ring-yellow-200 font-medium";
        default: return "bg-white text-gray-900 border-gray-300";
    }
  };

  return (
    <div className="max-w-7xl mx-auto p-4 sm:p-6 space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">לוח בקרה למרצה</h1>
          <p className="text-gray-500 mt-1">ניהול פרויקט תיוג ומעקב אחר התקדמות הסטודנטים</p>
        </div>
        <div className="flex gap-3">
             <Button 
                onClick={() => setShowAssignModal(true)}
                variant='neutral'
                className="flex items-center gap-2 bg-purple-100 text-purple-700 border border-purple-200 hover:bg-purple-200"
            >
                <Shuffle className="w-4 h-4" />
                שיוך אוטומטי
            </Button>
             <Button 
                onClick={() => setActiveTab('dashboard')} 
                variant={activeTab === 'dashboard' ? 'primary' : 'secondary'}
                className="flex items-center gap-2"
            >
                <BarChart2 className="w-4 h-4" />
                דשבורד
            </Button>
            <Button 
                onClick={() => setActiveTab('upload')} 
                variant={activeTab === 'upload' ? 'primary' : 'secondary'}
                className="flex items-center gap-2"
            >
                <Upload className="w-4 h-4" />
                העלאת ציוצים
            </Button>
        </div>
      </div>

      {/* Tweet Detail / Edit Modal */}
      {editingTweet && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4 animate-fadeIn">
              <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full flex flex-col max-h-[90vh]">
                  {/* Modal Header */}
                  <div className="flex justify-between items-center px-6 py-4 border-b border-gray-100 bg-gray-50 rounded-t-xl">
                      <div className="flex items-center gap-2">
                        <span className="bg-blue-100 text-blue-800 text-xs font-bold px-2 py-1 rounded">
                           ID: {editingTweet.id}
                        </span>
                        <h3 className="text-lg font-bold text-gray-900">עריכת ציוץ</h3>
                      </div>
                      <button onClick={() => setEditingTweet(null)} className="text-gray-400 hover:text-gray-600 transition-colors">
                          <X className="w-6 h-6" />
                      </button>
                  </div>
                  
                  {/* Modal Body (Scrollable) */}
                  <div className="flex-1 overflow-y-auto p-6 space-y-6">
                      {/* Tweet Text */}
                      <div className="bg-gray-50 p-6 rounded-xl border border-gray-100">
                          <p className="text-lg leading-relaxed text-gray-800 font-medium">"{editingTweet.text}"</p>
                      </div>

                      {/* Conflict Alert */}
                      {hasConflict(editingTweet) && (
                          <div className="flex items-start gap-3 bg-red-50 p-4 rounded-lg border border-red-100 text-red-700">
                              <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                              <div>
                                  <p className="font-bold">זוהתה התנגשות בסיווגים</p>
                                  <p className="text-sm opacity-90">הסטודנטים סיווגו ציוץ זה בקטגוריות שונות.</p>
                                  <div className="mt-2 text-xs bg-white p-2 rounded border border-red-100">
                                      {Object.entries(editingTweet.annotations).map(([student, label]) => (
                                          <div key={student} className="flex justify-between mb-1 last:mb-0">
                                              <span className="font-medium">{student}:</span>
                                              <span>{label}</span>
                                          </div>
                                      ))}
                                  </div>
                              </div>
                          </div>
                      )}

                      {/* Student List & Assignment */}
                      <div>
                          <h4 className="font-bold text-gray-700 mb-3 flex items-center gap-2">
                              <Users className="w-4 h-4" />
                              ניהול שיוכים וסיווגים
                          </h4>
                          <div className="bg-blue-50 p-3 rounded-lg mb-4 text-xs text-blue-800">
                              סמן בתיבת הסימון (Checkbox) כדי לשייך את הציוץ לסטודנט.
                          </div>
                          <div className="space-y-3">
                              {/* List all students, but highlight those assigned */}
                              {availableStudents.length > 0 ? availableStudents.map(student => {
                                  const isAssigned = editingTweet.assignedTo?.includes(student) || false;
                                  const currentLabel = editingTweet.annotations[student];
                                  
                                  if (!isAssigned && selectedStudentFilter !== 'all') return null;

                                  return (
                                      <div 
                                        key={student} 
                                        className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                                            isAssigned ? 'bg-white border-gray-200 shadow-sm' : 'bg-gray-50 border-gray-100 opacity-75'
                                        }`}
                                      >
                                          <div className="flex items-center gap-4">
                                              {/* Checkbox for assignment */}
                                              <input 
                                                type="checkbox" 
                                                checked={isAssigned}
                                                onChange={() => handleToggleAssignment(student)}
                                                className="w-5 h-5 text-blue-600 rounded focus:ring-blue-500 cursor-pointer"
                                                title={`שייך/בטל שיוך עבור ${student}`}
                                              />
                                              
                                              <div className="flex items-center gap-3">
                                                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${
                                                      isAssigned ? 'bg-blue-100 text-blue-700' : 'bg-gray-200 text-gray-500'
                                                  }`}>
                                                      {student.charAt(0).toUpperCase()}
                                                  </div>
                                                  <div>
                                                      <p className={`font-medium ${isAssigned ? 'text-gray-900' : 'text-gray-500'}`}>
                                                          {student}
                                                      </p>
                                                      {!isAssigned && <span className="text-xs text-gray-400">לא משויך</span>}
                                                  </div>
                                              </div>
                                          </div>

                                          <div className="w-48">
                                              <select
                                                value={currentLabel || ""}
                                                onChange={(e) => onAdminLabelChange(editingTweet.id, student, e.target.value)}
                                                disabled={!isAssigned}
                                                className={`block w-full text-sm border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 ${getLabelColor(currentLabel)} disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200`}
                                                >
                                                <option value="" disabled className="bg-white text-gray-500">
                                                    {isAssigned ? 'טרם סווג' : '-'}
                                                </option>
                                                {Object.values(LabelOption).map((option) => (
                                                    <option key={option} value={option} className="bg-white text-gray-900">{option}</option>
                                                ))}
                                                </select>
                                          </div>
                                      </div>
                                  );
                              }) : (
                                  <p className="text-gray-500 text-sm italic">לא נמצאו סטודנטים רשומים במערכת.</p>
                              )}
                          </div>
                      </div>
                  </div>

                  {/* Modal Footer */}
                  <div className="p-4 bg-gray-50 border-t border-gray-100 rounded-b-xl flex justify-between">
                      <Button onClick={() => handleDeleteClick(editingTweet.id)} variant="danger" className="text-sm bg-red-100 hover:bg-red-200 hover: shadow-none">
                          <Trash2 className="w-4 h-4 ml-2" />
                          מחק ציוץ
                      </Button>
                      <Button onClick={() => setEditingTweet(null)}>סגור</Button>
                  </div>
              </div>
          </div>
      )}

      {/* Auto Assign Modal */}
      {showAssignModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4 animate-fadeIn">
              <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full p-6">
                  <div className="flex justify-between items-center mb-6 border-b pb-4">
                      <h3 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                          <Shuffle className="w-5 h-5 text-purple-600" />
                          שיוך אוטומטי
                      </h3>
                      <button onClick={() => setShowAssignModal(false)} className="text-gray-400 hover:text-gray-600">
                          <X className="w-6 h-6" />
                      </button>
                  </div>
                  
                  <div className="space-y-6">
                      <div className="bg-blue-50 p-4 rounded-lg text-sm text-blue-800 flex items-start gap-3">
                          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                          <div>
                            פעולה זו תחלק את כל הציוצים ש<strong>טרם שויכו</strong> בין הסטודנטים הנבחרים.
                            נמצאו {tweets.filter(t => !t.assignedTo || t.assignedTo.length === 0).length} ציוצים פנויים.
                          </div>
                      </div>

                      <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">בחר סטודנטים משתתפים:</label>
                          <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto border p-2 rounded">
                              {availableStudents.length > 0 ? availableStudents.map(student => (
                                  <label key={student} className="flex items-center gap-2 p-2 border rounded hover:bg-gray-50 cursor-pointer">
                                      <input 
                                        type="checkbox" 
                                        checked={assignmentConfig.selectedStudents.includes(student)}
                                        onChange={(e) => {
                                            const isChecked = e.target.checked;
                                            setAssignmentConfig(prev => ({
                                                ...prev,
                                                selectedStudents: isChecked 
                                                    ? [...prev.selectedStudents, student]
                                                    : prev.selectedStudents.filter(s => s !== student)
                                            }));
                                        }}
                                        className="rounded text-blue-600 focus:ring-blue-500"
                                      />
                                      <span className="text-sm text-gray-900 font-medium">{student}</span>
                                  </label>
                              )) : (
                                  <p className="col-span-2 text-sm text-gray-500 text-center p-2">לא נמצאו סטודנטים רשומים.</p>
                              )}
                          </div>
                      </div>

                      <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                              אחוז חפיפה ({assignmentConfig.overlapPercentage}%)
                          </label>
                          <p className="text-xs text-gray-500 mb-3">אחוז הציוצים שיקבלו בדיקה כפולה (שני סטודנטים) לבדיקת אמינות.</p>
                          <input 
                            type="range" 
                            min="0" 
                            max="100" 
                            step="5"
                            value={assignmentConfig.overlapPercentage}
                            onChange={(e) => setAssignmentConfig(prev => ({ ...prev, overlapPercentage: Number(e.target.value) }))}
                            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                          />
                          <div className="flex justify-between text-xs text-gray-400 mt-1">
                              <span>0% (ללא חפיפה)</span>
                              <span>100% (חפיפה מלאה)</span>
                          </div>
                      </div>

                      <div className="pt-4 flex justify-end gap-3">
                          <Button variant="secondary" onClick={() => setShowAssignModal(false)}>ביטול</Button>
                          <Button onClick={handleAutoAssign} className="bg-purple-600 hover:bg-purple-700">
                              <Play className="w-4 h-4 ml-2" />
                              בצע שיוך
                          </Button>
                      </div>
                  </div>
              </div>
          </div>
      )}

      {activeTab === 'upload' ? (
          <div className="space-y-8">
             {/* Info Box */}
             <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-start gap-3">
                 <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                 <div>
                     <h4 className="font-bold text-blue-800 text-sm mb-1">הנחיות לטעינת קובץ (CSV/TXT)</h4>
                     <ul className="text-xs text-blue-700 space-y-1 list-disc list-inside">
                         <li>המערכת תומכת בקבצי טקסט פשוטים.</li>
                         <li>כל שורה בקובץ תזוהה כציוץ חדש.</li>
                         <li>אין צורך בכותרות, אך אם השורה הראשונה היא 'text' או 'tweet', המערכת תסנן אותה.</li>
                         <li>מומלץ להסיר תווים מיוחדים שעלולים לשבש את הקריאה.</li>
                     </ul>
                 </div>
             </div>

             {/* Input Section */}
             <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                <div className="flex flex-col md:flex-row gap-8">
                   {/* Paste Text Area */}
                   <div className="flex-1">
                      <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
                        <FileText className="w-5 h-5 text-blue-600" />
                        הדבקת טקסט חופשי
                      </h3>
                      <div className="space-y-3">
                        <textarea 
                            className="w-full h-32 p-3 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            placeholder="הדבק ציוצים כאן (כל ציוץ בשורה חדשה)..."
                            value={pasteText}
                            onChange={(e) => setPasteText(e.target.value)}
                        ></textarea>
                        <Button onClick={handleTextToDraft} disabled={!pasteText.trim()} className="w-full sm:w-auto">
                           הוסף לטיוטה
                        </Button>
                      </div>
                   </div>

                   <div className="w-px bg-gray-200 hidden md:block"></div>

                   {/* CSV Upload */}
                   <div className="flex-1">
                      <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
                        <FileSpreadsheet className="w-5 h-5 text-green-600" />
                        העלאת קובץ CSV
                      </h3>
                      <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:bg-gray-50 transition-colors">
                         <input 
                           type="file" 
                           accept=".csv,.txt"
                           ref={fileInputRef}
                           onChange={handleFileUpload}
                           className="hidden"
                           id="file-upload"
                         />
                         <label htmlFor="file-upload" className="cursor-pointer block">
                            <Upload className="w-10 h-10 text-gray-400 mx-auto mb-2" />
                            <p className="text-sm text-gray-600 font-medium">לחץ לבחירת קובץ</p>
                            <p className="text-xs text-gray-400 mt-1">תומך ב-CSV או TXT</p>
                         </label>
                      </div>
                   </div>
                </div>
             </div>

             {/* Staging / Draft Area */}
             {draftTweets.length > 0 && (
               <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden animate-fadeIn">
                  <div className="p-4 bg-blue-50 border-b border-blue-100 flex flex-col sm:flex-row justify-between items-center gap-4">
                     <div className="flex items-center gap-2">
                        <div className="bg-blue-600 text-white w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm">
                          {draftTweets.length}
                        </div>
                        <h3 className="font-bold text-blue-900">ציוצים בטיוטה (ממתינים לשמירה)</h3>
                     </div>

                     <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-blue-200 shadow-sm">
                           <span className="text-xs text-gray-500">שייך הכל ל:</span>
                           {availableStudents.map(student => (
                              <button 
                                key={student}
                                onClick={() => bulkAssignDrafts(student)}
                                className="text-xs bg-gray-100 hover:bg-blue-100 text-gray-700 hover:text-blue-700 px-2 py-1 rounded transition-colors"
                              >
                                + {student}
                              </button>
                           ))}
                        </div>
                        <Button onClick={clearAllDrafts} variant="danger" className="text-xs px-3 py-2">
                           <Trash2 className="w-4 h-4" />
                        </Button>
                     </div>
                  </div>

                  <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50 sticky top-0 z-10 shadow-sm">
                        <tr>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-12">#</th>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">תוכן הציוץ</th>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-64">שיוך לסטודנטים</th>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-20"></th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {draftTweets.map((draft, idx) => (
                          <tr key={draft.tempId} className="hover:bg-gray-50 group">
                            <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-400">{idx + 1}</td>
                            <td className="px-6 py-4 text-sm text-gray-900">
                               {draft.text}
                            </td>
                            <td className="px-6 py-4 text-sm">
                               <div className="flex flex-wrap gap-2">
                                  {availableStudents.map(student => {
                                    const isSelected = draft.assignedTo.includes(student);
                                    return (
                                      <button
                                        key={student}
                                        onClick={() => toggleDraftAssignment(draft.tempId, student)}
                                        className={`px-2 py-1 rounded text-xs border transition-all ${
                                          isSelected 
                                            ? 'bg-blue-100 border-blue-300 text-blue-700 font-medium' 
                                            : 'bg-white border-gray-200 text-gray-500 hover:border-gray-400'
                                        }`}
                                      >
                                        {student}
                                      </button>
                                    );
                                  })}
                               </div>
                               {draft.assignedTo.length === 0 && (
                                 <span className="text-xs text-red-400 mt-1 block">לא משויך</span>
                               )}
                            </td>
                            <td className="px-6 py-4 text-right">
                               <button 
                                 onClick={() => removeDraft(draft.tempId)}
                                 className="text-gray-400 hover:text-red-600 transition-colors opacity-0 group-hover:opacity-100"
                               >
                                 <X className="w-5 h-5" />
                               </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="p-4 bg-gray-50 border-t border-gray-200 flex justify-end">
                     <Button onClick={saveDraftsToSystem} className="flex items-center gap-2 pl-6 pr-6 shadow-md">
                        <CheckSquare className="w-4 h-4" />
                        שמור {draftTweets.length} ציוצים במערכת
                     </Button>
                  </div>
               </div>
             )}
          </div>
      ) : (
        <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Quick Stats Cards */}
                <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 flex items-center gap-4">
                <div className="p-3 bg-blue-100 rounded-full text-blue-600">
                    <FileText className="w-6 h-6" />
                </div>
                <div>
                    <p className="text-sm font-medium text-gray-500">סה"כ ציוצים</p>
                    <p className="text-2xl font-bold text-gray-900">{tweets.length}</p>
                </div>
                </div>
                
                <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 flex items-center gap-4">
                <div className="p-3 bg-purple-100 rounded-full text-purple-600">
                    <Users className="w-6 h-6" />
                </div>
                <div>
                    <p className="text-sm font-medium text-gray-500">סטודנטים פעילים</p>
                    <p className="text-2xl font-bold text-gray-900">{studentStats.length}</p>
                </div>
                </div>

                <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 flex items-center gap-4">
                <div className="p-3 bg-green-100 rounded-full text-green-600">
                    <CheckSquare className="w-6 h-6" />
                </div>
                <div>
                    <p className="text-sm font-medium text-gray-500">סה"כ תיוגים</p>
                    <p className="text-2xl font-bold text-gray-900">
                    {studentStats.reduce((acc, curr) => acc + curr.labeledCount, 0)}
                    </p>
                </div>
                </div>
            </div>

            {/* Student Progress Table - Now Full Width */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
                    <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                    <Users className="w-5 h-5 text-gray-500" />
                    התקדמות סטודנטים
                    </h3>
                </div>
                <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">שם סטודנט</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">שויכו</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">תויגו</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">נותרו</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">הושלם</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {studentStats.length > 0 ? (
                        studentStats.map((stat) => (
                            <tr key={stat.name} className="hover:bg-gray-50">
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{stat.name}</td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{stat.totalAssigned}</td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{stat.labeledCount}</td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{Math.max(0, stat.totalAssigned - stat.labeledCount)}</td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                <div className="flex items-center gap-2">
                                <div className="w-16 bg-gray-200 rounded-full h-1.5">
                                    <div 
                                    className="bg-blue-600 h-1.5 rounded-full" 
                                    style={{ width: stat.totalAssigned > 0 ? `${(stat.labeledCount / stat.totalAssigned) * 100}%` : '0%' }}
                                    ></div>
                                </div>
                                <span className="text-xs">
                                    {stat.totalAssigned > 0 ? Math.round((stat.labeledCount / stat.totalAssigned) * 100) : 0}%
                                </span>
                                </div>
                            </td>
                            </tr>
                        ))
                        ) : (
                        <tr>
                            <td colSpan={5} className="px-6 py-8 text-center text-gray-500 text-sm">
                            אין עדיין נתונים להצגה
                            </td>
                        </tr>
                        )}
                    </tbody>
                    </table>
                </div>
            </div>

            {/* Detailed Classification Management Table */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                    <Edit3 className="w-5 h-5 text-gray-500" />
                    ניהול ועריכת סיווגים
                    </h3>
                    <p className="text-sm text-gray-500 mt-1">
                        מוצגים {filteredTweets.length} ציוצים
                        {showConflictsOnly && <span className="text-red-500 mr-1 font-bold">(סינון התנגשויות פעיל)</span>}
                    </p>
                </div>
                
                <div className="flex flex-wrap items-center gap-3">
                     
                     <div className="flex items-center gap-2 border-l pl-3 ml-1">
                         <button 
                             onClick={() => setShowConflictsOnly(!showConflictsOnly)}
                             className={`flex items-center gap-1 text-sm px-3 py-1.5 rounded-md border transition-colors ${
                                 showConflictsOnly 
                                 ? 'bg-red-50 text-red-700 border-red-200' 
                                 : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                             }`}
                         >
                             <AlertTriangle className="w-3.5 h-3.5" />
                             {showConflictsOnly ? 'הצג הכל' : 'הצג התנגשויות'}
                         </button>
                     </div>

                     {/* Filters */}
                    <div className="flex items-center gap-2">
                            <select 
                                value={selectedLabelFilter}
                                onChange={(e) => setSelectedLabelFilter(e.target.value)}
                                className="block w-full pl-2 pr-8 py-1.5 text-sm border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 rounded-md"
                            >
                                <option value="all">כל התיוגים</option>
                                {Object.values(LabelOption).map(opt => (
                                    <option key={opt} value={opt}>{opt}</option>
                                ))}
                            </select>
                    </div>

                    <div className="flex items-center gap-2">
                            <select 
                                value={selectedStudentFilter}
                                onChange={(e) => setSelectedStudentFilter(e.target.value)}
                                className="block w-full pl-2 pr-8 py-1.5 text-sm border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 rounded-md"
                            >
                                <option value="all">כל הסטודנטים</option>
                                {allStudentNames.map(name => (
                                    <option key={name} value={name}>{name}</option>
                                ))}
                            </select>
                    </div>

                     <Button onClick={handleExport} variant="secondary" className="flex items-center gap-2 text-sm py-1.5 h-full">
                        <Download className="w-4 h-4" />
                        ייצוא
                    </Button>
                </div>
                </div>
                
                {allStudentNames.length > 0 ? (
                <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-20">מזהה</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider max-w-xs">תוכן הציוץ</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-32">משויך ל:</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-40">התקדמות</th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-64">סיווגים נוכחיים</th>
                         <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                            פעולות
                        </th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {filteredTweets.map((tweet) => {
                            const isConflict = hasConflict(tweet);
                            const assignedCount = tweet.assignedTo?.length || 0;
                            const labeledCount = Object.keys(tweet.annotations).filter(k => tweet.assignedTo?.includes(k)).length;
                            
                            // Check for 'Unsure/Skip' labels
                            const unsureStudents = Object.entries(tweet.annotations)
                                .filter(([_, label]) => label === LabelOption.Skip)
                                .map(([student]) => student);
                            const hasUnsure = unsureStudents.length > 0;

                            // Prepare conflict tooltip details
                            const conflictDetails = Object.entries(tweet.annotations)
                                .map(([s, l]) => `${s}: ${l}`)
                                .join('\n');

                            // Prepare Label Distribution for summary column
                            const labelsDistribution = Object.entries(tweet.annotations).reduce((acc, [student, label]) => {
                                if (!acc[label]) acc[label] = [];
                                acc[label].push(student);
                                return acc;
                            }, {} as Record<string, string[]>);

                            return (
                                <tr key={tweet.id} className={`hover:bg-gray-50 ${isConflict ? 'bg-red-50 hover:bg-red-100' : ''}`}>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 align-top">
                                        {tweet.id}
                                        {isConflict && (
                                            <div 
                                                title={`התנגשות בין מתייגים:\n${conflictDetails}`} 
                                                className="text-red-500 mt-1 cursor-help flex items-center gap-1 bg-white rounded-full px-1 border border-red-200 shadow-sm w-fit"
                                            >
                                                <AlertTriangle className="w-3 h-3" />
                                                <span className="text-[10px] font-bold">התנגשות</span>
                                            </div>
                                        )}
                                        {hasUnsure && (
                                            <div 
                                                title={`סומן כ'לא בטוח' על ידי: ${unsureStudents.join(', ')}`} 
                                                className="text-yellow-600 mt-1 cursor-help flex items-center gap-1 bg-yellow-50 rounded-full px-2 py-0.5 border border-yellow-200 shadow-sm w-fit"
                                            >
                                                <HelpCircle className="w-3 h-3" />
                                                <span className="text-[10px] font-bold">לא בטוח</span>
                                            </div>
                                        )}
                                    </td>
                                    <td className="px-6 py-4 text-sm text-gray-900 max-w-xs align-top">
                                        <div className="line-clamp-2 hover:line-clamp-none cursor-pointer transition-all" title={tweet.text}>
                                            {tweet.text}
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-xs text-gray-500 align-top">
                                        <div className="flex flex-wrap gap-1">
                                            {tweet.assignedTo?.map(s => (
                                                <span key={s} className="bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                                                    {s}
                                                </span>
                                            ))}
                                            {!tweet.assignedTo?.length && <span className="text-gray-400 italic">לא משויך</span>}
                                        </div>
                                    </td>
                                    
                                    <td className="px-6 py-4 whitespace-nowrap text-sm align-top">
                                            <div className="flex items-center gap-2 mb-1">
                                                <div className="flex-1 h-2 bg-gray-200 rounded-full w-20">
                                                    <div 
                                                    className="h-2 bg-blue-600 rounded-full" 
                                                    style={{ width: assignedCount > 0 ? `${(labeledCount / assignedCount) * 100}%` : '0%'}}
                                                    ></div>
                                                </div>
                                                <span className="text-xs text-gray-500 font-medium">{labeledCount}/{assignedCount}</span>
                                            </div>
                                            {assignedCount > 0 && labeledCount === assignedCount && (
                                                <span className="text-[10px] text-green-600 font-bold bg-green-50 px-1.5 py-0.5 rounded border border-green-100">הושלם</span>
                                            )}
                                    </td>

                                    <td className="px-6 py-4 whitespace-nowrap text-sm align-top">
                                            {/* Colored Label Badges */}
                                            <div className="flex flex-wrap gap-1.5">
                                            {Object.entries(labelsDistribution).length > 0 ? Object.entries(labelsDistribution).map(([label, students]) => (
                                                <span 
                                                    key={label} 
                                                    title={`סומן על ידי: ${students.join(', ')}`} 
                                                    className={`text-[10px] px-2 py-0.5 rounded border shadow-sm cursor-help whitespace-nowrap ${getLabelColor(label)}`}
                                                >
                                                    {label} ({students.length})
                                                </span>
                                            )) : (
                                                <span className="text-xs text-gray-400">טרם החל תיוג</span>
                                            )}
                                            </div>
                                    </td>

                                    <td className="px-6 py-4 whitespace-nowrap text-sm align-top">
                                       <div className="flex items-center gap-2">
                                            <button 
                                                onClick={() => setEditingTweet(tweet)}
                                                className="text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 p-2 rounded-md transition-colors"
                                                title="צפה בפרטים וערוך"
                                            >
                                                <Maximize2 className="w-4 h-4" />
                                            </button>
                                            <button 
                                                onClick={() => handleDeleteClick(tweet.id)}
                                                className="text-red-500 hover:text-red-700 bg-red-50 hover:bg-red-100 p-2 rounded-md transition-colors"
                                                title="מחק ציוץ"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                       </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                    </table>
                </div>
                ) : (
                <div className="text-center py-12 text-gray-500">
                    <Users className="w-12 h-12 mx-auto mb-2 opacity-20" />
                    <p>לא נמצאו סטודנטים פעילים במערכת</p>
                </div>
                )}
            </div>
        </>
      )}
    </div>
  );
};