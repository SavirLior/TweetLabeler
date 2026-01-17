import React, { useState } from 'react';
import { User, UserRole } from '../types';
import { Button } from './Button';
import { UserCircle, UserPlus, LogIn, Lock, Key } from 'lucide-react';
import { authenticateUser, registerUser } from '../services/dataService';

interface LoginProps {
  onLogin: (user: User) => void;
}

const ADMIN_SECRET_CODE = "secret";

export const Login: React.FC<LoginProps> = ({ onLogin }) => {
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>(UserRole.Student);
  const [adminCode, setAdminCode] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    if (!username || !password) {
      setError('נא למלא את כל השדות');
      setIsLoading(false);
      return;
    }

    // Validate Admin Code if registering as Admin
    if (isRegistering && role === UserRole.Admin) {
        if (adminCode !== ADMIN_SECRET_CODE) {
            setError('קוד גישה למנהל שגוי');
            setIsLoading(false);
            return;
        }
    }

    try {
      if (isRegistering) {
        const newUser: User = { username, password, role };
        await registerUser(newUser);
        onLogin(newUser);
      } else {
        const user = await authenticateUser(username, password);
        if (user) {
          onLogin(user);
        } else {
          setError('שם משתמש או סיסמה שגויים');
        }
      }
    } catch (err: any) {
      setError(err.message || 'אירעה שגיאה');
    } finally {
      setIsLoading(false);
    }
  };

  const toggleMode = () => {
    setIsRegistering(!isRegistering);
    setError('');
    setUsername('');
    setPassword('');
    setRole(UserRole.Student);
    setAdminCode('');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4" dir="rtl">
      <div className="max-w-md w-full bg-white rounded-lg shadow-xl overflow-hidden p-8 border border-gray-100">
        <div className="flex flex-col items-center mb-8">
          <div className="bg-blue-100 p-4 rounded-full mb-4 ring-4 ring-blue-50">
            {isRegistering ? (
               <UserPlus className="w-10 h-10 text-blue-600" />
            ) : (
               <Lock className="w-10 h-10 text-blue-600" />
            )}
          </div>
          <h2 className="text-2xl font-bold text-gray-900 text-center">
            {isRegistering ? 'הרשמה למערכת' : 'כניסה למערכת'}
          </h2>
          <p className="text-gray-500 text-center mt-2 text-sm">
            {isRegistering ? 'צור משתמש חדש כדי להתחיל' : 'אנא הזן פרטי התחברות'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              שם משתמש
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="הכנס שם משתמש"
              autoComplete="username"
              disabled={isLoading}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              סיסמה
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="הכנס סיסמה"
              autoComplete="current-password"
              disabled={isLoading}
            />
          </div>

          {isRegistering && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                תפקיד
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                disabled={isLoading}
              >
                <option value={UserRole.Student}>סטודנט (מתייג)</option>
                <option value={UserRole.Admin}>מנהל (מרצה)</option>
              </select>
              
              {role === UserRole.Admin && (
                  <div className="mt-4 bg-yellow-50 p-4 rounded-md border border-yellow-100 animate-fadeIn">
                      <label className="block text-sm font-medium text-yellow-800 mb-1 flex items-center gap-1">
                         <Key className="w-4 h-4" />
                         קוד גישה למנהל
                      </label>
                      <input
                        type="password"
                        value={adminCode}
                        onChange={(e) => setAdminCode(e.target.value)}
                        className="block w-full px-3 py-2 border border-yellow-300 rounded-md shadow-sm focus:outline-none focus:ring-yellow-500 focus:border-yellow-500 text-sm"
                        placeholder="הכנס את הקוד הסודי"
                        autoComplete="off"
                        disabled={isLoading}
                      />
                      <p className="text-xs text-yellow-600 mt-1">
                          נדרש קוד מיוחד להרשמה כמנהל.
                      </p>
                  </div>
              )}
              
              {role !== UserRole.Admin && (
                  <p className="text-xs text-gray-400 mt-1">בחר "מנהל" רק אם אתה המרצה האחראי.</p>
              )}
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm p-3 rounded-md flex items-center justify-center">
              {error}
            </div>
          )}

          <Button type="submit" disabled={isLoading} className="w-full justify-center py-2.5 text-base shadow-md disabled:opacity-70">
            {isLoading ? 'מעבד נתונים...' : (isRegistering ? 'הירשם' : 'התחבר')}
          </Button>

          <div className="text-center pt-2">
            <button
              type="button"
              onClick={toggleMode}
              disabled={isLoading}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium hover:underline transition-all disabled:opacity-50"
            >
              {isRegistering 
                ? 'יש לך כבר חשבון? התחבר כאן' 
                : 'אין לך חשבון? הירשם כאן'}
            </button>
          </div>
        </form>
        
        {/* {!isRegistering && (
           <div className="mt-8 pt-6 border-t border-gray-100 text-center">
             <p className="text-xs text-gray-400">
               חשבונות ברירת מחדל:<br/>
               admin / 123<br/>
               student1 / 123
             </p>
           </div>
        )} */}
      </div>
    </div>
  );
};