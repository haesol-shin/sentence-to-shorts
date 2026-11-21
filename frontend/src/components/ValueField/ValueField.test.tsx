import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { ValueField, type ValueFieldItem } from './ValueField';

afterEach(cleanup);

const ITEMS: readonly ValueFieldItem[] = [
  { value: 'bright', label: '밝은 목소리' },
  { value: 'calm', label: '차분한 목소리' },
  {
    value: 'robot',
    label: '로봇 목소리',
    unavailable: true as const,
    unavailableName: 'Robot voice, coming soon',
    tag: <span>곧 지원</span>,
  },
];

describe('ValueField', () => {
  test('test_10a_value_field_opens_with_one_named_field_and_its_options', () => {
    render(<ValueField label="목소리" items={ITEMS} defaultValue="calm" defaultOpen />);

    const trigger = screen.getByRole('combobox', { name: '목소리' });
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getAllByRole('option')).toHaveLength(3);
    expect(screen.getByRole('option', { name: '차분한 목소리' }).getAttribute('aria-selected')).toBe(
      'true',
    );
  });

  test('test_10a_value_field_unavailable_option_is_described_by_the_note', () => {
    render(<ValueField label="목소리" items={ITEMS} note="Opens in a later step." defaultOpen />);

    const option = screen.getByRole('option', { name: 'Robot voice, coming soon' });
    const describedBy = option.getAttribute('aria-describedby');
    expect(option.getAttribute('aria-disabled')).toBe('true');
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy ?? '')?.textContent).toContain(
      'Opens in a later step.',
    );
  });

  test('test_10a_value_field_placeholder_is_shown_when_no_value_is_chosen', () => {
    render(<ValueField label="목소리" items={ITEMS} placeholder="목소리 고르기" />);

    expect(screen.getByRole('combobox', { name: '목소리' }).textContent).toContain(
      '목소리 고르기',
    );
  });
});
