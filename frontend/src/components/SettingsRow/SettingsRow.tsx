import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './SettingsRow.css';

export type SettingsRowProps = {
  label: ReactNode;
  description?: ReactNode;
  /** The control the caller composes: a Switch, a ValueField, a TextField. */
  control: ReactNode;
  /** A visible reason or state mark, for example the unavailable tag and sentence. */
  note?: ReactNode;
  className?: string;
};

/** One labelled setting. The row itself is not a control; the control inside is. */
export function SettingsRow({ label, description, control, note, className }: SettingsRowProps) {
  return (
    <div className={cn('settings-row', className)}>
      <div className="settings-row__text">
        <span className="settings-row__label">{label}</span>
        {description === undefined ? null : (
          <span className="settings-row__description">{description}</span>
        )}
        {note === undefined ? null : <span className="settings-row__note">{note}</span>}
      </div>
      <div className="settings-row__control">{control}</div>
    </div>
  );
}
