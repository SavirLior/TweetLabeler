FROM node:20-bullseye

# Install Python for the Flask API.
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5173 8080

# Run both the API and the Vite dev server.
CMD ["bash", "-lc", "python3 server.py & npm run dev -- --host 0.0.0.0 --port 5173"]
