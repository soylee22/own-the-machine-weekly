import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:4321/own-the-machine-weekly/',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'phone', use: { ...devices['iPhone 13'] } },
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
  ],
  reporter: [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
});
