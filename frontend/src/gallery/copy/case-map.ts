/**
 * The copy keys a gallery case renders, and the exact case that renders them.
 *
 * The case renderer reads the same key constants, so a key can only link to a
 * case that draws it. The case-map test checks the keys the renderer handles.
 */

export const COMPOSER_COPY_KEYS = {
  send: 'shell.first.send',
  error: 'concept.composer.fileTooMany',
  remove: 'concept.composer.attachmentRemove',
  addLink: 'concept.composer.addLink',
  addBgm: 'concept.composer.addBgm',
} as const;

export type CopyCaseSpec = {
  partId: string;
  /** The case slug inside the part, for example `attachments`. */
  slug: string;
};

export const COPY_CASES: Readonly<Record<string, CopyCaseSpec>> = {
  [COMPOSER_COPY_KEYS.send]: { partId: 'composer', slug: 'default' },
  [COMPOSER_COPY_KEYS.error]: { partId: 'composer', slug: 'attachments' },
  [COMPOSER_COPY_KEYS.remove]: { partId: 'composer', slug: 'attachments' },
  [COMPOSER_COPY_KEYS.addLink]: { partId: 'menu', slug: 'open' },
  [COMPOSER_COPY_KEYS.addBgm]: { partId: 'menu', slug: 'open' },
};
