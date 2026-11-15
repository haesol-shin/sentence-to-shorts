import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { EditRoute } from '@/app/routes/edit';
import { LocaleProvider } from '@/shared/lib/i18n/locale';
import { StageScrollProvider } from '@/shared/lib/stage-scroll';

afterEach(cleanup);

function renderEdit(scrolled: boolean): void {
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <StageScrollProvider scrolled={scrolled}>
        <EditRoute />
      </StageScrollProvider>
    </LocaleProvider>,
  );
}

const preview = () => document.querySelector('[data-slot="preview"]');

test('test_10a_the_edit_preview_stays_open_at_the_top', () => {
  renderEdit(false);
  expect(preview()?.getAttribute('data-collapsed')).toBeNull();
});

test('test_10a_scrolling_the_stage_folds_the_edit_preview', () => {
  renderEdit(true);
  expect(preview()?.getAttribute('data-collapsed')).toBe('true');
});
