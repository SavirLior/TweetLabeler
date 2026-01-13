# Stage 1: Build the frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: Serve with Python
FROM python:3.11-slim
WORKDIR /app

# התקנת ספריות מערכת נחוצות (אם צריך)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/ports/lists/*

# העתקת דרישות והתקנה
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- החלק החדש עבור ה-DB ---
# יצירת התיקייה ומתן הרשאות כתיבה
RUN mkdir -p /app/db && chmod 777 /app/db

# העתקת שאר הקבצים
COPY --from=frontend-build /app/dist ./dist
COPY server.py .
COPY services/ ./services/
COPY *.json .

# פקודת ההרצה
CMD ["python", "server.py"]