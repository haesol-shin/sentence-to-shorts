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

test('test_14_the_http_track_catalog_lists_uploaded_and_code_tracks_with_their_source', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  const sources: Record<string, [string, string]> = {
    upload_1: ['upload', 'tense'],
    code_1: ['code', 'playful'],
  };
  vi.stubGlobal('fetch', async (input: string) => {
    const path = new URL(input, 'https://app.invalid');
    if (path.pathname === '/api/v1/catalog/bgm') {
      return Response.json({
        items: Object.keys(sources).map((id) => ({ id, label: { ko: id, en: id }, revision: 'b'.repeat(64) })),
        next_cursor: null,
      });
    }
    const [source, mood] = sources[path.pathname.split('/').at(-1) ?? ''] ?? ['builtin', 'calm'];
    return Response.json({ mood, source, accepted_at: '2026-01-15T12:00:00Z' });
  });

  const tracks = await createEditApi().listBgm('v_fixture');
  expect(tracks.map(({ id, mood, source }) => [id, mood, source])).toEqual([
    ['upload_1', 'tense', 'upload'], ['code_1', 'playful', 'code'],
  ]);
});

test('test_14_every_http_track_previews_through_the_bgm_audio_route', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  const fetched = vi.fn();
  vi.stubGlobal('fetch', fetched);

  const api = createEditApi();
  const urls = await Promise.all(['builtin_loop', 'upload_1', 'code_1'].map((id) => api.previewUrl('bgm', id)));
  expect(urls).toEqual([
    '/api/v1/bgm/builtin_loop/audio', '/api/v1/bgm/upload_1/audio', '/api/v1/bgm/code_1/audio',
  ]);
  expect(fetched).not.toHaveBeenCalled();
});
