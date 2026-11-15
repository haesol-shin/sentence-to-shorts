import js from '@eslint/js';
import boundaries from 'eslint-plugin-boundaries';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const sharedLayers = ['shared', 'shared-lib', 'shared-ui', 'shared-api'];

export default tseslint.config(
  {
    ignores: [
      'dist/',
      'node_modules/',
      'playwright-report/',
      'test-results/',
      // Generated API types are rewritten by `npm run gen:api` (CONTRACTS 0).
      'src/shared/api/generated/',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      boundaries,
    },
    settings: {
      'boundaries/elements': [
        { type: 'app', pattern: 'src/app', partialMatch: false },
        { type: 'feature', pattern: 'src/features/*', partialMatch: false },
        { type: 'shared-lib', pattern: 'src/shared/lib', partialMatch: false },
        { type: 'shared-ui', pattern: 'src/shared/ui', partialMatch: false },
        { type: 'shared-api', pattern: 'src/shared/api', partialMatch: false },
        { type: 'shared', pattern: 'src/shared', partialMatch: false },
        { type: 'components', pattern: 'src/components', partialMatch: false },
        { type: 'gallery', pattern: 'src/gallery', partialMatch: false },
      ],
      'import/resolver': {
        typescript: { alwaysTryTypes: true, project: './tsconfig.json' },
      },
    },
    rules: {
      'boundaries/no-unknown-files': 'error',
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          policies: [
            {
              from: { element: { type: 'app' } },
              allow: {
                to: {
                  element: {
                    types: ['feature', 'components', ...sharedLayers],
                  },
                },
              },
            },
            {
              from: { element: { type: 'feature' } },
              allow: {
                to: {
                  element: {
                    types: ['components', ...sharedLayers],
                  },
                },
              },
            },
            {
              from: { element: { types: sharedLayers } },
              allow: { to: { element: { types: sharedLayers } } },
            },
            {
              from: { element: { type: 'components' } },
              allow: { to: { element: { type: 'shared-lib' } } },
            },
            {
              from: { element: { type: 'gallery' } },
              allow: {
                to: {
                  element: {
                    types: ['components', 'shared', 'shared-lib', 'shared-ui'],
                  },
                },
              },
            },
          ],
        },
      ],
    },
  },
  {
    files: ['vite.config.ts', 'playwright.config.ts', 'eslint.config.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
);
