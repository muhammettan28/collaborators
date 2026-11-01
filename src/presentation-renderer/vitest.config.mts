import { defineConfig } from 'vitest/config';

// The unit suite: `__tests__/*.spec.ts`. Only browser.spec.ts drives a real
// browser, and only when CHROMIUM_PATH names one (it is skipped otherwise).
export default defineConfig({
  test: {
    include: ['__tests__/**/*.spec.ts'],
    env: {
      JWKS_URL: 'http://backend:8000/api/v1.0/jwks',
    },
    isolate: true,
    clearMocks: true,
    testTimeout: 60000,
  },
});
