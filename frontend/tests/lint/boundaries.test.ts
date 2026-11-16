import { ESLint } from 'eslint';
import { describe, expect, test } from 'vitest';

const violation = [
  "import { getJson } from '@/shared/api/client';",
  "import type { paths } from '@/shared/api/generated/openapi';",
  '',
  'export type ContractPaths = paths;',
  'export const client = getJson;',
  '',
].join('\n');

const allowed = [
  "import { cn } from '@/shared/lib/utils';",
  '',
  "export const className = cn('p-4');",
  '',
].join('\n');

async function lintAt(filePath: string, source: string) {
  const eslint = new ESLint();
  const [result] = await eslint.lintText(source, { filePath });
  return result.messages;
}

describe('frontend import boundaries', () => {
  test('test_2_components_cannot_import_shared_api', async () => {
    const messages = await lintAt(
      'src/components/boundary-violation.ts',
      violation,
    );

    const boundaryErrors = messages.filter(
      (message) => message.ruleId === 'boundaries/dependencies',
    );

    expect(boundaryErrors.length).toBeGreaterThan(0);
    expect(messages.map((message) => message.message).join('\n')).toContain(
      'shared-api',
    );
  }, 30_000);

  test('test_2_components_can_import_shared_lib', async () => {
    const messages = await lintAt('src/components/boundary-allowed.ts', allowed);

    expect(messages).toEqual([]);
  }, 30_000);
});
