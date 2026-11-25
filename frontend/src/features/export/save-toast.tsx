import { useEffect, useState, useSyncExternalStore } from 'react';

import { Toast } from '@/components/Toast/Toast';
import { useLocale } from '@/shared/lib/i18n/locale';

import { readSaved, subscribeSaved } from './download';
import './export.css';

/** How long the save notice stays on screen. */
const SHOWN_MS = 3000;

/**
 * The notice after a save button: the file went to the downloads folder. A
 * second save of the same file shows it again for the full time.
 */
export function SaveToast() {
  const { t } = useLocale();
  const saved = useSyncExternalStore(subscribeSaved, readSaved, readSaved);
  const [shown, setShown] = useState<number | null>(null);
  // A save from before this mount was announced already.
  const [mountedAt] = useState(() => readSaved()?.token ?? 0);

  useEffect(() => {
    if (saved === null || saved.token <= mountedAt) return undefined;
    setShown(saved.token);
    const timer = window.setTimeout(() => setShown(null), SHOWN_MS);
    return () => window.clearTimeout(timer);
  }, [saved, mountedAt]);

  return (
    <Toast open={saved !== null && shown === saved.token} className="export-save-toast">
      {saved === null ? null : t(`export.save.saved.${saved.kind}`)}
    </Toast>
  );
}
