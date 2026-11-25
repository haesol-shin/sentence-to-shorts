/** The copy editor's one-line error text; the checks themselves live in the gallery rule module. */

export {
  checkCopy,
  placeholders,
  type CopyError,
  type CopyErrorCode,
  type CopyCheckInput,
} from './rules';

/** The one line the editor shows under a failing row. */
export function errorLine(errors: readonly { message: string }[]): string {
  if (errors.length === 0) return '검사 통과';
  return `저장 안 됨: ${errors.map((error) => error.message).join(' · ')}`;
}
