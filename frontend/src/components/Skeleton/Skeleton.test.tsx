import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Skeleton } from './Skeleton';

afterEach(cleanup);

describe('Skeleton', () => {
  test('test_10a_skeleton_keeps_the_measured_shapes', () => {
    const { container } = render(
      <>
        <Skeleton shape="thumb" />
        <Skeleton shape="script" />
        <Skeleton shape="media" />
      </>,
    );

    const blocks = [...container.querySelectorAll<HTMLElement>('.skeleton')];
    expect(blocks.map((block) => block.getAttribute('data-shape'))).toEqual(['thumb', 'script', 'media']);
    for (const block of blocks) expect(block.getAttribute('aria-hidden')).toBe('true');
  });
});
