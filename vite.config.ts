import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // זה החלק שמאפשר ל-ngrok לעבוד
    allowedHosts: true,
  },
});
