import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, test } from 'vitest';

/**
 * The screens use the approved parts and the role tokens, and the neutral
 * wireframe parts are gone. These read the source, because a screen that
 * imports an unapproved part still renders.
 */
const SRC = join(process.cwd(), 'src');
const SCREEN_ROOTS = [join(SRC, 'app'), join(SRC, 'features')];

function filesUnder(root: string, extensions: readonly string[]): string[] {
  const found: string[] = [];
  for (const name of readdirSync(root)) {
    const path = join(root, name);
    if (statSync(path).isDirectory()) found.push(...filesUnder(path, extensions));
    else if (extensions.some((extension) => name.endsWith(extension))) found.push(path);
  }
  return found;
}

function screenFiles(extensions: readonly string[]): string[] {
  return SCREEN_ROOTS.flatMap((root) => filesUnder(root, extensions));
}

function importsOf(path: string): string[] {
  const source = readFileSync(path, 'utf8');
  return [...source.matchAll(/^import\s[^;]*?from\s+'([^']+)';/gms)].map((match) => match[1] ?? '');
}

function readSrc(path: string): string {
  return readFileSync(join(SRC, path), 'utf8');
}

/** The declarations of the first rule whose selector is exactly `selector`. */
function declarationsOf(css: string, selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const rule = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm').exec(css);
  expect(rule, `${selector} is missing`).not.toBeNull();
  const values: Record<string, string> = {};
  for (const line of (rule?.[1] ?? '').split(';')) {
    const [name, ...rest] = line.split(':');
    if (name !== undefined && rest.length > 0) values[name.trim()] = rest.join(':').trim();
  }
  return values;
}

describe('screens use the approved parts', () => {
  test('test_23_screens_import_only_approved_components', () => {
    const approved = new Set(
      readdirSync(join(SRC, 'components')).filter((name) =>
        existsSync(join(SRC, 'components', name, `${name}.tsx`)),
      ),
    );
    expect(approved.size).toBeGreaterThan(0);

    const offenders: string[] = [];
    for (const path of screenFiles(['.ts', '.tsx'])) {
      for (const specifier of importsOf(path)) {
        const part = /^@\/components\/([^/]+)\/([^/]+)$/.exec(specifier);
        const direct = specifier.startsWith('@/components') || specifier.includes('/components/');
        if (direct && (part === null || part[1] !== part[2] || !approved.has(part[1] ?? ''))) {
          offenders.push(`${relative(SRC, path)}: ${specifier}`);
        }
        if (/^@\/shared\/ui\/(?!tokens\.css$)/.test(specifier)) {
          offenders.push(`${relative(SRC, path)}: ${specifier}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  test('test_23_shared_ui_keeps_no_wireframe_part', () => {
    expect(readdirSync(join(SRC, 'shared', 'ui'))).toEqual(['tokens.css']);
  });

  test('test_23_only_tokens_css_holds_color_values', () => {
    const color = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|color-mix)\(/;
    const offenders: string[] = [];
    for (const path of screenFiles(['.css', '.tsx'])) {
      // A mask gradient only needs any opaque value; it paints nothing.
      const source = readFileSync(path, 'utf8').replaceAll('linear-gradient(#000 0 0)', '');
      if (color.test(source)) offenders.push(relative(SRC, path));
    }
    expect(offenders).toEqual([]);
  });

  test('test_23_playback_controls_use_the_approved_play_row', () => {
    for (const path of ['features/edit/scene-preview.tsx', 'features/export/result-player.tsx']) {
      const source = readSrc(path);
      expect(source, path).toContain("from '@/components/PlaybackControls/PlaybackControls'");
      expect(source, path).not.toMatch(
        /import\s*\{[^}]*\b(?:Play|Pause|CirclePlay|PlayCircle)\b[^}]*\}\s*from 'lucide-react'/,
      );
    }
  });

  test('test_23_script_jump_control_takes_the_secondary_button_state_colors', () => {
    const button = readSrc('components/Button/Button.css');
    const script = readSrc('features/script/script.css');
    const jump = '.script-document-pane .scroll-pane__jump .icon-button';

    const secondary = declarationsOf(button, '.button--secondary');
    const hover = declarationsOf(button, ".button--secondary:hover:not(:disabled),\n.button--secondary[data-force-state~='hover']:not(:disabled)");
    const pressed = declarationsOf(button, ".button--secondary:active:not(:disabled),\n.button--secondary[data-force-state~='pressed']:not(:disabled)");

    const rest = declarationsOf(script, jump);
    expect(rest.background).toBe(secondary.background);
    expect(rest['border-color']).toBe(secondary['border-color']);
    expect(rest.color).toBe(secondary.color);
    expect(declarationsOf(script, `${jump}:hover:not(:disabled)`).background).toBe(hover.background);
    expect(declarationsOf(script, `${jump}:active:not(:disabled)`).background).toBe(pressed.background);

    // The script cards sit on the part's grey; the jump control must not match it.
    const card = declarationsOf(script, '.script-card');
    expect(rest.background).not.toBe(card.background);
  });
});
