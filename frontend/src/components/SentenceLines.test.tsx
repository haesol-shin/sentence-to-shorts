import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { SentenceLines } from './SentenceLines';

afterEach(cleanup);

describe('SentenceLines', () => {
  test('test_10a_sentence_lines_start_each_sentence_on_its_own_line', () => {
    const { container } = render(
      <p>
        <SentenceLines>연결이 끊겼어요. 다시 시도해 주세요.</SentenceLines>
      </p>,
    );

    expect(container.querySelectorAll('br')).toHaveLength(1);
    expect(container.textContent).toBe('연결이 끊겼어요. 다시 시도해 주세요.');
  });

  test('test_10a_sentence_lines_keep_a_single_sentence_inline', () => {
    const { container } = render(
      <p>
        <SentenceLines>연결을 확인해 주세요.</SentenceLines>
      </p>,
    );

    expect(container.querySelectorAll('br')).toHaveLength(0);
    expect(container.textContent).toBe('연결을 확인해 주세요.');
  });
});
