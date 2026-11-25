const SIGNAL_CODES = { SIGHUP: 129, SIGINT: 130, SIGTERM: 143 };

/** The shell exit code a signal-ending child should produce. */
export function signalExitCode(signal) {
  return SIGNAL_CODES[signal] ?? 1;
}
