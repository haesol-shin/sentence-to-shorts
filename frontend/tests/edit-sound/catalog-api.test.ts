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

test('test_24_the_http_caption_layout_sends_the_trial_values_and_returns_the_server_answer', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  const layout = { primary_px: 22, extra_px: 28, pairs: [{ primary: 'top', extra: 'bottom', fits: true }] };
  const fetched = vi.fn(async () => Response.json(layout));
  vi.stubGlobal('fetch', fetched);
  const api = createEditApi();
  const font = { id: 'galmuri14', revision: 'c'.repeat(64) };

  expect(await api.captionLayout('v_fixture', { font: null, extraLanguage: 'en', extraFont: font })).toEqual(layout);
  const url = new URL(String((fetched.mock.calls[0] as unknown as [string])[0]), 'https://app.invalid');
  expect(url.pathname).toBe('/api/v1/videos/v_fixture/caption-layout');
  expect([...url.searchParams.keys()]).toEqual(['extra_language', 'extra_font_id']);
  expect(url.searchParams.get('extra_language')).toBe('en');
  expect(JSON.parse(url.searchParams.get('extra_font_id') ?? '')).toEqual(font);

  await api.captionLayout('v_fixture', { font: null, extraLanguage: null, extraFont: null });
  const plain = new URL(String((fetched.mock.calls[1] as unknown as [string])[0]), 'https://app.invalid');
  expect(plain.search).toBe('');
});

test('test_24_a_rejected_http_request_keeps_the_semantic_errors_of_the_problem', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  const errors = [{ code: 'caption_overlap', pointer: '/scenes/s_1/lines/0' }];
  vi.stubGlobal('fetch', async () =>
    Response.json({ code: 'invalid_combination', message_key: 'error.invalid_combination', errors }, { status: 422 }),
  );
  await expect(createEditApi().captionLayout('v_fixture', { font: null, extraLanguage: null, extraFont: null })).rejects.toMatchObject({
    code: 'invalid_combination',
    status: 422,
    errors,
  });
});

test('test_24_the_http_template_limit_follows_the_dialog_box_and_the_sandbox_renderer', async () => {
  vi.stubEnv('VITE_API_MODE', 'http');
  const templates: Record<string, { dialog_box: boolean; renderer: { kind: string } }> = {
    dialog_stage: { dialog_box: true, renderer: { kind: 'builtin' } },
    made_by_user: { dialog_box: false, renderer: { kind: 'sandbox' } },
    fixed_stage: { dialog_box: false, renderer: { kind: 'builtin' } },
  };
  vi.stubGlobal('fetch', async (input: string) =>
    Response.json(templates[new URL(input, 'https://app.invalid').pathname.split('/').at(-1) ?? '']),
  );
  const api = createEditApi();
  expect(await Promise.all(Object.keys(templates).map((id) => api.templateSingleLayer(id)))).toEqual([
    true,
    true,
    false,
  ]);
});
