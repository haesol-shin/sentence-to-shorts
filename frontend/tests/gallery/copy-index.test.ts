import { describe, expect, test } from 'vitest';

import { buildCopyIndex } from '../../vite-plugins/copy-index';

describe('copy index', () => {
  const index = buildCopyIndex(process.cwd());
  const shell = index.files.find((file) => file.namespace === 'shell');
  const concept = index.files.find((file) => file.namespace === 'concept');

  test('test_10a_copy_index_lists_every_locale_file', () => {
    expect(index.editable).toBe(false);
    expect(index.files.map((file) => file.namespace)).toEqual([
      'shell',
      'concept',
      'script',
      'edit',
      'export',
      'audio',
      'errors',
    ]);
    expect(shell?.koKeys.length).toBeGreaterThan(0);
  });

  test('test_10a_copy_index_maps_only_the_cases_that_render_the_key', () => {
    const apiKey = shell?.entries.find((entry) => entry.key === 'apiKey.save');
    expect(apiKey?.cases).toEqual([]);
    expect(apiKey?.usages.some((usage) => usage.path === 'src/app/api-key-block.tsx')).toBe(true);

    const send = shell?.entries.find((entry) => entry.key === 'first.send');
    expect(send?.cases.map((item) => item.partId)).toEqual(['composer']);

    const fileTooMany = concept?.entries.find((entry) => entry.key === 'composer.fileTooMany');
    expect(fileTooMany?.cases.map((item) => item.partId)).toEqual(['composer']);
    expect(fileTooMany?.cases[0]?.label).toBe('18-7-attachments');

    const attachmentRemove = concept?.entries.find(
      (entry) => entry.key === 'composer.attachmentRemove',
    );
    expect(attachmentRemove?.cases[0]?.label).toBe('18-7-attachments');

    const addLink = concept?.entries.find((entry) => entry.key === 'composer.addLink');
    expect(addLink?.cases.map((item) => item.partId)).toEqual(['menu']);
    const addBgm = concept?.entries.find((entry) => entry.key === 'composer.addBgm');
    expect(addBgm?.cases.map((item) => item.partId)).toEqual(['menu']);
  });

  test('test_10a_copy_index_finds_a_key_declared_in_a_data_table', () => {
    const nav = shell?.entries.find((entry) => entry.key === 'nav.newVideo');
    expect(nav?.cases).toEqual([]);
    expect(nav?.usages.some((usage) => usage.path === 'src/app/shell/sidebar.tsx')).toBe(true);
  });
});
