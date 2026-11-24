/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    coverage: {
      provider: 'v8',
      // Every source file of the HMI is counted, including the files that no
      // test touches. Without this, the untested SCADA views would silently
      // disappear from the report and the coverage figure would look far
      // better than the reality.
      include: ['src/**/*.{ts,tsx}'],
      all: true,
      reporter: ['text', 'json', 'html'],
      // The enforced floors are the measured coverage of the current test
      // suite (4.15 % lines, 5.95 % functions, 0 % branches) with a small
      // margin. They are a regression guard, not a quality claim.
      //
      // The roadmap target of 75 % is documented in docs/CI_CD_GUIDE.md. It
      // can only be reached once the SCADA view components have component
      // tests; until then a 75 % threshold would be a gate that is always
      // red and therefore never enforced.
      thresholds: {
        lines: 4,
        functions: 5,
        statements: 4,
        // No branch of the HMI is covered yet, so there is no branch floor to
        // enforce. A zero threshold means "no requirement" in Vitest.
        branches: 0,
        // The two modules that do have tests are guarded tightly, so that new
        // uncovered code in them is caught even when the global figure moves
        // very little.
        'src/services/api.ts': {
          lines: 18,
          functions: 38,
          statements: 18,
          branches: 0,
        },
        'src/services/auth.ts': {
          lines: 11,
          functions: 0,
          statements: 11,
          branches: 0,
        },
      },
    },
  },
});
