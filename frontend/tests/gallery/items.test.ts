import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, test } from 'vitest';

import {
  SHARED_PART_IDS,
  galleryParts,
  inlineCases,
  portalCases,
  type GalleryPart,
} from '../../src/gallery/items';

type MatrixPart = {
  part: string;
  states: string[];
  variants?: Record<string, unknown>;
  skip?: Record<string, string>;
};

const tokens = JSON.parse(
  readFileSync(join(process.cwd(), '..', 'design', 'tokens', 'tokens.json'), 'utf8'),
) as { states: { parts: MatrixPart[] } };

const matrix = new Map(tokens.states.parts.map((part) => [part.part, part]));

function primaryMatrix(part: GalleryPart): MatrixPart {
  const row = matrix.get(part.matrixPart);
  if (row === undefined) throw new Error(`unknown matrix part: ${part.matrixPart}`);
  return row;
}

describe('gallery state list', () => {
  test('test_10a_gallery_lists_every_shared_part_of_batch_one', () => {
    expect(galleryParts.map((part) => part.id)).toEqual([...SHARED_PART_IDS]);
    for (const part of galleryParts) {
      expect(part.batch).toBe(1);
      expect(part.cases.length).toBeGreaterThan(0);
    }
  });

  test('test_10a_gallery_numbers_are_generated_in_order_and_unique', () => {
    const labels = new Set<string>();
    galleryParts.forEach((part, partIndex) => {
      expect(part.number).toBe(partIndex + 1);
      part.cases.forEach((entry, caseIndex) => {
        expect(entry.label.startsWith(`${partIndex + 1}-${caseIndex + 1}-`)).toBe(true);
        expect(labels.has(entry.label)).toBe(false);
        labels.add(entry.label);
      });
    });
    expect(labels.size).toBe(galleryParts.reduce((sum, part) => sum + part.cases.length, 0));
  });

  test('test_10a_gallery_shows_every_matrix_state_and_variant', () => {
    for (const part of galleryParts) {
      if (part.matrixPart === '') continue;
      const row = primaryMatrix(part);
      for (const state of row.states) {
        expect(
          part.cases.some((entry) => entry.state === state),
          `${part.id} ${state}`,
        ).toBe(true);
      }
      for (const variant of Object.keys(row.variants ?? {})) {
        expect(
          part.cases.some((entry) => entry.variant === variant),
          `${part.id} variant ${variant}`,
        ).toBe(true);
      }
    }
    for (const name of galleryParts.flatMap((part) => part.matrixParts)) {
      expect(matrix.has(name), name).toBe(true);
    }
  });

  test('test_10a_gallery_records_the_reason_for_every_state_the_matrix_skips', () => {
    for (const part of galleryParts) {
      if (part.matrixPart === '') continue;
      const row = primaryMatrix(part);
      const skip = row.skip ?? {};
      expect(Object.keys(part.notApplicable).sort()).toEqual(Object.keys(skip).sort());
      for (const reason of Object.values(part.notApplicable)) {
        expect(reason.length).toBeGreaterThan(0);
      }
    }
  });

  test('test_10a_gallery_marks_only_popups_as_portal_cases', () => {
    for (const part of galleryParts) {
      for (const entry of [...inlineCases(part), ...portalCases(part)]) {
        if (entry.portal) {
          expect(entry.label.includes('open') || entry.label.includes('item') || part.id === 'tooltip').toBe(
            true,
          );
        }
      }
    }
  });
});
