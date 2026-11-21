import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Button } from '../Button/Button';
import { MenuButton, type MenuItemSpec } from './MenuButton';

afterEach(cleanup);

const ITEMS: readonly MenuItemSpec[] = [
  { value: 'upload', label: '참고 영상 올리기' },
  {
    value: 'image',
    label: '이미지 올리기',
    unavailable: true as const,
    unavailableName: 'Image upload, coming soon',
    tag: <span>곧 지원</span>,
  },
];

describe('MenuButton', () => {
  test('test_10a_menu_opens_with_a_name_and_the_trigger_reports_it', () => {
    render(
      <MenuButton
        trigger={<Button variant="trigger">파일 넣기</Button>}
        label="파일 넣기"
        heading="파일 넣기"
        items={ITEMS}
        defaultOpen
      />,
    );

    expect(screen.getByRole('menu', { name: '파일 넣기' })).toBeTruthy();
    const trigger = screen.getByRole('button', { name: '파일 넣기' });
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
  });

  test('test_10a_menu_unavailable_row_keeps_its_reason_visible', () => {
    render(
      <MenuButton
        trigger={<Button variant="trigger">파일 넣기</Button>}
        label="파일 넣기"
        items={ITEMS}
        note="Opens in a later step."
        defaultOpen
      />,
    );

    const row = screen.getByRole('menuitem', { name: 'Image upload, coming soon' });
    expect(row.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Opens in a later step.')).toBeTruthy();
  });

  test('test_10a_menu_lists_every_row', () => {
    render(
      <MenuButton
        trigger={<Button variant="trigger">파일 넣기</Button>}
        label="파일 넣기"
        items={ITEMS}
        defaultOpen
      />,
    );

    expect(screen.getAllByRole('menuitem')).toHaveLength(2);
  });
});
