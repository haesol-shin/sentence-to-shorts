import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Tag } from './Tag';

afterEach(cleanup);

describe('Tag', () => {
  test('test_10a_tag_keeps_the_tone_on_its_icon', () => {
    render(
      <Tag variant="warning" icon={<span aria-hidden="true">!</span>}>
        주의
      </Tag>,
    );

    const tag = screen.getByText('주의').closest('.tag');
    expect(tag?.getAttribute('data-variant')).toBe('warning');
    expect(tag?.querySelector('.tag__icon')).not.toBeNull();
  });

  test('test_10a_tag_defaults_to_the_neutral_variant', () => {
    render(<Tag>곧 지원</Tag>);

    expect(screen.getByText('곧 지원').closest('.tag')?.getAttribute('data-variant')).toBe(
      'neutral',
    );
  });
});
