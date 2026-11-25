import { describe, expect, test } from 'vitest';

import { signalExitCode } from '../../vite-plugins/exit-code.mjs';

describe('dev wrapper exit code', () => {
  test('test_10a_dev_wrapper_reports_a_signal_as_a_failure', () => {
    expect(signalExitCode('SIGTERM')).toBe(143);
    expect(signalExitCode('SIGINT')).toBe(130);
    expect(signalExitCode('SIGHUP')).toBe(129);
    expect(signalExitCode('SIGKILL')).toBe(1);
    expect(signalExitCode(null)).toBe(1);
  });
});
