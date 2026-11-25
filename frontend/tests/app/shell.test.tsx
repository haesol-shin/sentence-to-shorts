import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { DRAFT_JOB_PATH, draftJob, shellRoutes } from '../support/api';
import { renderApp, sendSentence } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('test_10a_sidebar_names_an_icon_on_hover', async () => {
  await renderApp();
  const icon = screen.getByRole('button', { name: '새로 만들기' });

  expect(screen.queryByRole('tooltip')).toBeNull();

  fireEvent.pointerEnter(icon, { pointerType: 'mouse' });
  fireEvent.mouseEnter(icon);
  fireEvent.mouseMove(icon);
  expect((await screen.findByRole('tooltip')).textContent).toContain('새로 만들기');

  fireEvent.pointerLeave(icon, { pointerType: 'mouse' });
  fireEvent.mouseLeave(icon);
  await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());
});

test('test_10a_sidebar_names_an_icon_on_keyboard_focus', async () => {
  await renderApp();
  const icon = screen.getByRole('button', { name: '새로 만들기' });

  icon.focus();

  expect((await screen.findByRole('tooltip')).textContent).toContain('새로 만들기');
});

test('test_10a_first_screen_shows_no_step_indicator', async () => {
  await renderApp();

  expect(document.querySelector('[data-slot="stage-indicator"]')).toBeNull();
  expect(document.querySelector('[data-slot="stage-menu"]')).toBeNull();
});

test('test_10a_step_tabs_show_three_steps_and_export_keeps_edit_current', async () => {
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const tabs = () => screen.getByRole('navigation', { name: '단계' });
  const current = () => tabs().querySelector('[aria-current="step"]')?.textContent;
  expect([...tabs().querySelectorAll('button')].map((tab) => tab.textContent)).toEqual(['컨셉', '대본', '편집']);
  expect(current()).toBe('컨셉');

  fireEvent.click(within(tabs()).getByRole('button', { name: '편집' }));
  expect(current()).toBe('편집');

  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '내보내기' }));
  expect(current()).toBe('편집');
});

test('test_10a_the_next_action_keeps_its_seat_on_stage_screens', async () => {
  await renderApp();
  expect(document.querySelector('[data-slot="next-action"]')).toBeNull();

  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const action = document.querySelector<HTMLButtonElement>('[data-slot="next-action"]');
  expect(action?.disabled).toBe(true);
});

test('test_10a_top_bar_names_the_video_and_its_menu_starts_a_new_one', async () => {
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const title = document.querySelector<HTMLButtonElement>('[data-slot="video-title"]');
  expect(title?.textContent).toBe('커피를 고르는 세 가지 기준');
  fireEvent.click(title!);
  const menu = await screen.findByRole('menu', { name: '영상 메뉴' });
  expect(menu.textContent).toContain('커피를 고르는 세 가지 기준');

  fireEvent.click(within(menu).getByRole('menuitem', { name: '새로 만들기' }));
  await screen.findByRole('heading', { name: '한 문장으로 영상을 만들어요' });
  expect(document.querySelector('[data-slot="top-bar"]')).toBeNull();
});

test('test_10a_the_conversation_opens_with_the_sent_sentence', async () => {
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: { ...draftJob, state } });
  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const conversation = document.querySelector<HTMLElement>('[data-slot="conversation"]')!;
  const said = conversation.querySelector('[data-slot="chat-user"]');
  expect(said?.textContent).toBe('커피를 고르는 세 가지 기준');
  // The concept line waits for the draft, so the step never claims a pick it has not made.
  expect(conversation.textContent).not.toContain('이야기 방식은');
  // The wait is said in the conversation, so the work area never shifts for a banner.
  expect(conversation.textContent).toContain('문장으로 컨셉 초안을 쓰고 있어요.');

  state = 'succeeded';
  await waitFor(() => expect(conversation.textContent).toContain(
    '이야기 방식은 딱 3가지만으로 골랐어요.',
  ), {
    timeout: 5000,
  });
  expect(conversation.textContent).toContain('길이는 1분, 장면은 8개로 했어요.');
  expect(conversation.textContent).toContain('그림체와 캐릭터는 기본값이에요.');
  expect(conversation.textContent).not.toContain('문장으로 컨셉 초안을 쓰고 있어요.');
});

test('test_10a_confirming_the_concept_opens_the_script_step', async () => {
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const footer = () => document.querySelector<HTMLElement>('footer.concept-footer')!;
  await waitFor(() => expect(within(footer()).getByRole<HTMLButtonElement>('button', { name: '정하고 대본 만들기' }).disabled).toBe(false));
  fireEvent.click(within(footer()).getByRole('button', { name: '정하고 대본 만들기' }));
  const dialog = document.querySelector<HTMLElement>('dialog.concept-dialog')!;
  fireEvent.click(within(dialog).getByRole('button', { name: '정하고 대본 만들기', hidden: true }));

  const tabs = screen.getByRole('navigation', { name: '단계' });
  await waitFor(() => expect(tabs.querySelector('[aria-current="step"]')?.textContent).toBe('대본'));
});

test('test_10a_brand_name_comes_from_the_runtime_answer', async () => {
  await renderApp();
  await waitFor(() =>
    expect(document.querySelector('[data-slot="brand"]')?.textContent).toBe('테스트 앱'),
  );
});
