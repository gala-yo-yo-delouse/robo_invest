import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// amplify_outputs.json lives one level up (written there by `ampx sandbox
// --outputs-out-dir web`), so allow Vite to read outside the web/ root.
export default defineConfig({
  plugins: [react()],
  server: { fs: { allow: ['..'] } },
});
