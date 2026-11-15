import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { Composer } from '@/app/shell/composer';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

afterEach(cleanup);

function renderComposer(onSubmit: () => void): HTMLElement {
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <Composer
        label="요청"
        placeholder="요청"
        sendLabel="보내기"
        value="한 문장"
        onChange={() => undefined}
        onSubmit={onSubmit}
      />
    </LocaleProvider>,
  );
  return screen.getByRole('textbox', { name: '요청' });
}

test('test_10a_enter_that_settles_a_composition_does_not_send', () => {
  const onSubmit = vi.fn();
  const box = renderComposer(onSubmit);

  fireEvent.keyDown(box, { key: 'Enter', isComposing: true });
  expect(onSubmit).not.toHaveBeenCalled();
  expect((box as HTMLTextAreaElement).value).toBe('한 문장');

  fireEvent.keyDown(box, { key: 'Enter' });
  expect(onSubmit).toHaveBeenCalledTimes(1);
});

test('test_10a_shift_enter_adds_a_line_instead_of_sending', () => {
  const onSubmit = vi.fn();
  const box = renderComposer(onSubmit);

  fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });

  expect(onSubmit).not.toHaveBeenCalled();
});
