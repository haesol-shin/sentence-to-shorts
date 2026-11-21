import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Button } from '../Button/Button';
import { BottomSheet } from './BottomSheet';

afterEach(cleanup);

describe('BottomSheet', () => {
  test('test_10a_sheet_opens_with_its_title_and_closes_on_escape', async () => {
    render(
      <BottomSheet
        title="목소리 고르기"
        closeLabel="Close"
        description="이 영상에서 쓸 목소리를 골라요."
        trigger={<Button variant="secondary">목소리</Button>}
        actions={<Button>적용</Button>}
      />,
    );

    const trigger = screen.getByRole('button', { name: '목소리' });
    fireEvent.click(trigger);

    expect(await screen.findByRole('dialog', { name: '목소리 고르기' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '목소리 고르기' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(trigger).toBe(document.activeElement));
  });
});
