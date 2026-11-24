import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { App } from '@/app/App';

import { shellRoutes, stubApi } from '../support/api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('test_4_app_renders_one_screen', async () => {
  stubApi(shellRoutes());
  const { container } = render(<App />);
  await screen.findByRole('heading', { name: '한 문장으로 영상을 만들어요' });

  expect(container.querySelector('main[data-screen="app"]')).not.toBeNull();
});
