import { createRef } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { ScrollPane } from './ScrollPane';

afterEach(cleanup);

function setMetrics(
  element: HTMLElement,
  metrics: { scrollHeight: number; clientHeight: number; scrollTop: number },
): void {
  for (const [name, value] of Object.entries(metrics)) {
    Object.defineProperty(element, name, { configurable: true, value });
  }
}

function pane(): HTMLElement {
  return screen.getByRole('region', { name: '대본' });
}

describe('ScrollPane', () => {
  test('test_10a_scroll_pane_names_its_region_and_keeps_the_jump_out_of_short_content', () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <ScrollPane ref={ref} label="대본" jumpLabel="Scroll down">
        <p>짧은 대본</p>
      </ScrollPane>,
    );

    expect(ref.current?.className).toContain('scroll-pane__viewport');
    expect(screen.getByText('짧은 대본')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Scroll down' })).toBeNull();
  });

  test('test_10a_scroll_pane_shows_the_jump_only_while_more_waits_below', () => {
    render(
      <ScrollPane label="대본" jumpLabel="Scroll down">
        <p>긴 대본</p>
      </ScrollPane>,
    );

    const viewport = pane();
    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });
    fireEvent.scroll(viewport);
    expect(screen.getByRole('button', { name: 'Scroll down' })).toBeTruthy();

    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 600 });
    fireEvent.scroll(viewport);
    expect(screen.queryByRole('button', { name: 'Scroll down' })).toBeNull();
  });

  test('test_10a_scroll_pane_keeps_the_jump_in_its_own_dock_outside_the_column', () => {
    render(
      <ScrollPane label="대본" jumpLabel="Scroll down">
        <p>긴 대본</p>
      </ScrollPane>,
    );

    const viewport = pane();
    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });
    fireEvent.scroll(viewport);
    const jump = screen.getByRole('button', { name: 'Scroll down' });

    expect(viewport.contains(jump)).toBe(false);
    expect(jump.closest('.scroll-pane__jump')?.parentElement).toBe(viewport.parentElement);
  });

  test('test_21_scroll_pane_jump_scrolls_to_the_very_bottom', () => {
    render(
      <ScrollPane label="대본" jumpLabel="Scroll down">
        <p>긴 대본</p>
      </ScrollPane>,
    );

    const viewport = pane();
    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });
    fireEvent.scroll(viewport);
    const scrollTo = vi.fn();
    Object.defineProperty(viewport, 'scrollTo', { configurable: true, value: scrollTo });

    fireEvent.click(screen.getByRole('button', { name: 'Scroll down' }));

    expect(scrollTo).toHaveBeenCalledWith({ top: 1000 });
  });

  test('test_10a_scroll_pane_gives_focus_back_when_the_jump_disappears', () => {
    render(
      <ScrollPane label="대본" jumpLabel="Scroll down">
        <p>긴 대본</p>
      </ScrollPane>,
    );

    const viewport = pane();
    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });
    fireEvent.scroll(viewport);
    const jump = screen.getByRole('button', { name: 'Scroll down' });
    jump.focus();
    expect(document.activeElement).toBe(jump);

    setMetrics(viewport, { scrollHeight: 1000, clientHeight: 400, scrollTop: 600 });
    fireEvent.scroll(viewport);

    expect(screen.queryByRole('button', { name: 'Scroll down' })).toBeNull();
    expect(document.activeElement).toBe(viewport);
  });
});
