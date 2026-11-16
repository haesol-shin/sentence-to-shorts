import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Button } from '../Button/Button';
import { Tooltip } from './Tooltip';

afterEach(cleanup);

describe('Tooltip', () => {
  test('test_10a_tooltip_opens_on_keyboard_focus_and_names_its_reason', async () => {
    render(
      <Tooltip content="아직 지원하지 않아요.">
        <Button variant="secondary">이유 보기</Button>
      </Tooltip>,
    );

    const trigger = screen.getByRole('button', { name: '이유 보기' });
    trigger.focus();
    const tooltip = await screen.findByRole('tooltip');

    expect(tooltip.textContent).toContain('아직 지원하지 않아요.');
    expect(trigger.getAttribute('aria-describedby')).toBe(tooltip.id);
  });

  test('test_10a_tooltip_can_be_forced_open_for_the_gallery', async () => {
    render(
      <Tooltip forceOpen content="곧 지원하는 기능이에요.">
        <Button variant="secondary">이유 보기</Button>
      </Tooltip>,
    );

    expect((await screen.findByRole('tooltip')).textContent).toContain('곧 지원하는 기능이에요.');
  });

  test('test_10a_tooltip_trigger_keeps_its_own_accessible_name', () => {
    render(
      <Tooltip content="이유">
        <Button variant="secondary">이유 보기</Button>
      </Tooltip>,
    );

    expect(screen.getByRole('button', { name: '이유 보기' }).getAttribute('aria-label')).toBeNull();
  });
});
