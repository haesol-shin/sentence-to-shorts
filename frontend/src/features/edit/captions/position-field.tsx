import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import { CAPTION_POSITIONS, type CaptionPosition } from './model';

/**
 * One layer's position menu. A position the server says would overlap stays in
 * the menu, dimmed, and cannot be picked; the note under the label says why.
 * The picked value is shown as it is even when it is dimmed.
 */
export function PositionField({
  label,
  description,
  value,
  blocked,
  disabled,
  note,
  onPick,
}: {
  label: string;
  description?: string;
  value: CaptionPosition;
  blocked: ReadonlySet<CaptionPosition>;
  disabled: boolean;
  note?: string;
  onPick: (position: CaptionPosition) => void;
}) {
  const { t } = useLocale();
  const items = CAPTION_POSITIONS.map((position) => ({
    value: position,
    label: t(`audio.caption.position.${position}`),
    disabled: blocked.has(position),
  }));
  return (
    <SettingsRow
      label={label}
      description={description}
      note={note}
      control={
        <ValueField
          label={label}
          items={items}
          value={value}
          disabled={disabled}
          onValueChange={(next) => {
            const position = CAPTION_POSITIONS.find((item) => item === next);
            if (position === undefined || position === value || blocked.has(position)) return;
            onPick(position);
          }}
        />
      }
    />
  );
}
