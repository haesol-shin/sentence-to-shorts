import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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

  test('test_10a_value_field_names_its_value_in_the_trigger_while_the_rows_keep_their_labels', () => {
    render(
      <ValueField
        label="목소리"
        name="목소리"
        display="차분함"
        items={ITEMS}
        defaultValue="calm"
        defaultOpen
      />,
    );

    expect(screen.getByRole('combobox', { name: '목소리' }).textContent).toMatch(/^목소리차분함/u);
    expect(screen.getByRole('option', { name: '차분한 목소리' }).textContent).toContain(
      '차분한 목소리',
    );
  });

  test('test_w0_value_field_takes_index_values_and_hands_the_same_value_back', () => {
    const seen: number[] = [];
    const rows: readonly ValueFieldItem<number>[] = [
      { value: 0, label: '첫째' },
      { value: 1, label: '둘째' },
      { value: 2, label: '셋째' },
    ];
    render(
      <ValueField<number>
        label="순서"
        items={rows}
        value={1}
        onValueChange={(next) => seen.push(next)}
        defaultOpen
      />,
    );

    expect(screen.getByRole('combobox', { name: '순서' }).textContent).toContain('둘째');
    expect(screen.getByRole('option', { name: '둘째' }).getAttribute('aria-selected')).toBe('true');
    const third = screen.getByRole('option', { name: '셋째' });
    // Base UI selects on the pointer sequence, which jsdom does not synthesize from a click alone.
    fireEvent.pointerDown(third);
    fireEvent.pointerUp(third);
    fireEvent.mouseUp(third);
    fireEvent.click(third);
    expect(seen).toEqual([2]);
  });

  test('test_w0_value_field_matches_values_that_are_not_strings_by_identity', () => {
    const rows: readonly ValueFieldItem<boolean | null>[] = [
      { value: true, label: '켜짐' },
      { value: false, label: '꺼짐' },
      { value: null, label: '자동' },
    ];
    render(<ValueField<boolean | null> label="모드" items={rows} value={null} />);
    expect(screen.getByRole('combobox', { name: '모드' }).textContent).toContain('자동');
    cleanup();
    render(<ValueField<boolean | null> label="모드" items={rows} value={false} />);
    expect(screen.getByRole('combobox', { name: '모드' }).textContent).toContain('꺼짐');
  });
});
