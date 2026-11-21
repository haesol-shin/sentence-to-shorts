import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { configureConceptApi } from '@/features/concept/store';
import { createHttpConceptApi } from '@/features/concept/http-api';

import { App } from './App';
import './index.css';

const root = document.getElementById('root');

if (root === null) {
  throw new Error('root element is missing');
}

async function start(): Promise<void> {
  if (import.meta.env.VITE_API_MODE === 'mock') {
    // Kept out of the real build by this branch: only a mock run loads fixtures.
    const { installMockApi } = await import('@/shared/api/mock');
    installMockApi();
  } else {
    configureConceptApi(createHttpConceptApi());
  }
  createRoot(root as HTMLElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
