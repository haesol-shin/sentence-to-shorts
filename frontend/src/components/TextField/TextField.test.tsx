import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { TextField } from './TextField';

afterEach(cleanup);

describe('TextField', () => {
  test('test_10a_text_field_labels_the_input_it_names', () => {
    render(<TextField label="API key" placeholder="API key를 붙여넣어 주세요" />);

    const input = screen.getByRole('textbox', { name: 'API key' });
    expect(input.getAttribute('placeholder')).toBe('API key를 붙여넣어 주세요');
  });

  test('test_10a_text_field_wires_the_error_sentence_to_the_input', () => {
    render(<TextField label="API key" error="API key를 찾을 수 없어요." />);

    const input = screen.getByRole('textbox', { name: 'API key' });
    const describedBy = input.getAttribute('aria-describedby');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(describedBy ?? '')?.textContent).toContain(
      'API key를 찾을 수 없어요.',
    );
  });

  test('test_10a_text_field_forced_disabled_disables_the_input', () => {
    render(<TextField label="API key" forceState="disabled" />);

    expect((screen.getByRole('textbox', { name: 'API key' }) as HTMLInputElement).disabled).toBe(
      true,
    );
  });
});
