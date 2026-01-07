# --- שלב 1: בניית ה-Frontend (Node.js) ---
    FROM node:20-alpine as frontend-build
    WORKDIR /app
    
    # העתקת הגדרות והתקנת ספריות JS
    COPY package*.json ./
    # דילוג על tsc כדי למנוע בעיות, בנייה ישירה
    RUN npm install
    
    # העתקת כל הקוד ובנייה
    COPY . .
    # זה ייצור את תיקיית dist בתוך הקונטיינר
    RUN npm run build
    
    # --- שלב 2: בניית ה-Backend והרצה (Python) ---
    FROM python:3.11-slim
    WORKDIR /app
    
    # התקנת ספריות Python
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    
    # --- הקסם קורה כאן: העתקת ה-dist מהשלב הראשון ---
    COPY --from=frontend-build /app/dist ./dist
    
    # העתקת קוד השרת
    COPY server.py .
    COPY services/ ./services/
    COPY *.json .
    # (אם יש לך עוד קבצים חשובים בתיקייה הראשית, וודא שהם מועתקים)
    
    # הגדרת משתני סביבה (אופציונלי)
    ENV FLASK_APP=server.py
    ENV PORT=8080
    
    # חשיפת הפורט
    EXPOSE 8080
    
    # הפעלת השרת על 0.0.0.0 (חשוב לדוקר!)
    CMD ["python", "server.py"]