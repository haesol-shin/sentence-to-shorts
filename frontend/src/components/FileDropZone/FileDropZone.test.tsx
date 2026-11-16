import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { FileDropZone } from './FileDropZone';

afterEach(cleanup);

describe('FileDropZone', () => {
  test('test_10a_file_drop_zone_names_the_action_and_the_kinds', () => {
    render(<FileDropZone open label="여기에 놓으면 올라가요" accept="영상, BGM, 글 파일(.md, .txt)" />);

    const zone = screen.getByRole('status');
    expect(zone.textContent).toContain('여기에 놓으면 올라가요');
    expect(zone.textContent).toContain('영상, BGM, 글 파일(.md, .txt)');
  });

  test('test_10a_file_drop_zone_container_scope_stays_in_its_parent', () => {
    const { container } = render(
      <div data-testid="drop-target" style={{ position: 'relative' }}>
        <FileDropZone scope="container" open label="여기에 놓으면 올라가요" accept="영상" />
      </div>,
    );

    const zone = screen.getByRole('status');
    expect(zone.classList.contains('file-drop--container')).toBe(true);
    expect(container.querySelector('[data-testid="drop-target"]')?.contains(zone)).toBe(true);
  });

  test('test_10a_file_drop_zone_is_absent_while_closed', () => {
    render(<FileDropZone open={false} label="여기에 놓으면 올라가요" accept="영상" />);

    expect(screen.queryByRole('status')).toBeNull();
  });
});
