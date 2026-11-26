/** One object guard for JSON boundaries in the gallery and its dev endpoint. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
