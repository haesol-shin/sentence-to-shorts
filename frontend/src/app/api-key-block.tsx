import { useState, type FormEvent } from 'react';

import { ApiProblemError, messageKeyOf } from '@/shared/api/client';
import { useLocale } from '@/shared/lib/i18n/locale';
import { Button } from '@/components/Button/Button';
import { Notice } from '@/components/Notice/Notice';
import { TextField } from '@/components/TextField/TextField';

/**
 * The release build asks for the user's own LLM key before the first video.
 * `noticeKey` is the `errors` key of the failure that brought the block back,
 * so a wrong key can be replaced next to the sentence that explains it.
 */
export function ApiKeyBlock({
  noticeKey,
  onSave,
}: {
  noticeKey: string | null;
  onSave: (apiKey: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [errorText, setErrorText] = useState<string | undefined>(undefined);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const apiKey = value.trim();
    if (apiKey === '' || saving) return;
    setSaving(true);
    setErrorText(undefined);
    try {
      await onSave(apiKey);
      setValue('');
    } catch (error) {
      setErrorText(
        error instanceof ApiProblemError && error.code === 'validation_failed'
          ? t('shell.apiKey.invalid')
          : error instanceof ApiProblemError && error.code === 'loopback_only'
            ? t('shell.apiKey.loopbackOnly')
            : t(`errors.${messageKeyOf(error)}`),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      data-slot="first-api-key"
      className="flex flex-col gap-3"
      onSubmit={(event) => void submit(event)}
    >
      {noticeKey === null ? null : <Notice tone="error">{t(`errors.${noticeKey}`)}</Notice>}
      <div className="flex flex-col gap-3">
        <TextField
          label={t('shell.apiKey.label')}
          type="password"
          name="api_key"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          error={errorText}
          disabled={saving}
        />
        <Button
          type="submit"
          className="self-end"
          disabled={saving || value.trim() === ''}
        >
          {t('shell.apiKey.save')}
        </Button>
      </div>
      <p className="text-[15px] text-[var(--text-muted)]">{t('shell.apiKey.hint')}</p>
    </form>
  );
}
