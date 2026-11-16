import { act, cleanup, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { renderApp, sendSentence } from '../support/render';

/**
 * A phone keyboard shrinks the visual viewport without resizing the layout
 * one. jsdom has no visual viewport, so this stands in for the phone.
 */
function installSoftKeyboard(): { open: () => void; close: () => void } {
  const handlers = new Set<() => void>();
  let open = false;
  const viewport = {
    get height() {
      return open ? window.innerHeight - 364 : window.innerHeight;
    },
    offsetTop: 0,
    addEventListener: (type: string, handler: () => void) => {
      if (type === 'resize' || type === 'scroll') {
        handlers.add(handler);
      }
    },
    removeEventListener: (type: string, handler: () => void) => {
      if (type === 'resize' || type === 'scroll') {
        handlers.delete(handler);
      }
    },
  };
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });

  const fire = () => {
    for (const handler of handlers) {
      handler();
    }
  };
  return {
    open: () => {
      open = true;
      fire();
    },
    close: () => {
      open = false;
      fire();
    },
  };
}

function jobStatusRegions(): HTMLElement[] {
  return [
    ...document.querySelectorAll<HTMLElement>('[data-slot="job-banner"], [data-slot="job-status"]'),
  ];
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('test_23_the_short_job_status_shows_in_the_top_bar_only_while_the_keyboard_is_open', async () => {
  const keyboard = installSoftKeyboard();
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  await waitFor(() => expect(document.querySelector('[data-slot="job-banner"]')).not.toBeNull());

  expect(document.querySelector('[data-slot="job-status"]')).toBeNull();

  act(() => keyboard.open());

  const status = document.querySelector('[data-slot="job-status"]');
  expect(status?.textContent).toBe('진행 상황 차례를 기다리는 중이에요.');
  expect(document.querySelector('[data-slot="top-bar"]')?.contains(status)).toBe(true);
  expect(document.querySelector('[data-slot="job-banner"]')).toBeNull();
});

test('test_23_one_job_status_live_region_moves_with_the_keyboard', async () => {
  const keyboard = installSoftKeyboard();
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  await waitFor(() => expect(jobStatusRegions()).toHaveLength(1));

  expect(jobStatusRegions()[0]?.closest('[data-slot="job-banner"]')).not.toBeNull();

  act(() => keyboard.open());
  expect(jobStatusRegions()).toHaveLength(1);
  expect(jobStatusRegions()[0]?.closest('[data-slot="top-bar"]')).not.toBeNull();

  act(() => keyboard.close());
  expect(jobStatusRegions()).toHaveLength(1);
  expect(jobStatusRegions()[0]?.closest('[data-slot="job-banner"]')).not.toBeNull();
  expect(document.querySelector('[data-slot="job-status"]')).toBeNull();
});

test('test_23_the_top_bar_stays_unchanged_while_the_keyboard_is_open_without_a_job', async () => {
  const keyboard = installSoftKeyboard();
  await renderApp();
  const before = document.querySelector('[data-slot="top-bar"]')?.innerHTML;

  act(() => keyboard.open());

  expect(document.querySelector('[data-slot="top-bar"]')?.innerHTML).toBe(before);
  expect(jobStatusRegions()).toHaveLength(0);
});
