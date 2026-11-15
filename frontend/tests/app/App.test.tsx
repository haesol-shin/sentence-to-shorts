import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { App } from '@/app/App';

afterEach(cleanup);

test('test_4_app_renders_one_screen', () => {
  const { container } = render(<App />);

  expect(container.querySelector('main[data-screen="app"]')).not.toBeNull();
});
