import { afterEach, expect, test, vi } from 'vitest';

import { createEditApi } from '@/features/edit/api';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

test('test_14_the_http_track_catalog_keeps_entries_after_the_first_page', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  vi.stubGlobal('fetch', async (input: string) => {
    const path = new URL(input, 'https://app.invalid');
    if (path.pathname === '/api/v1/catalog/bgm') {
      const second = path.searchParams.get('cursor') === '50';
      const id = second ? 'later' : 'first';
      return Response.json({
        items: [{ id, label: { ko: id, en: id }, revision: 'a'.repeat(64) }],
        next_cursor: second ? null : '50',
      });
    }
    return Response.json({
      mood: path.pathname.endsWith('/later') ? 'calm' : 'curious',
      source: 'builtin',
    });
  });

  const tracks = await createEditApi().listBgm('v_fixture');
  expect(tracks.map(({ id, mood }) => [id, mood])).toEqual([
    ['first', 'curious'], ['later', 'calm'],
  ]);
});
