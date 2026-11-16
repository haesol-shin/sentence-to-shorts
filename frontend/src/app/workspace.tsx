import { useEffect, useState } from 'react';

import {
  createProject,
  createVideo,
  messageKeyOf,
  submitDraft,
  type Language,
} from '@/shared/api/client';
import { useBrand } from '@/features/runtime/use-brand';
import { LocaleProvider, useLocale } from '@/shared/lib/i18n/locale';
import { useSession, type SessionResult } from '@/shared/lib/session';
import { useJob } from '@/shared/lib/use-job';
import { VisualViewportProvider } from '@/shared/lib/visual-viewport';
import { Notice } from '@/shared/ui/notice';

import { FirstScreen } from './first-screen';
import { ConceptRoute } from './routes/concept';
import { EditRoute } from './routes/edit';
import { ExportRoute } from './routes/export';
import { ScriptRoute } from './routes/script';
import { AppShell } from './shell/app-shell';
import { PlaceholderComposer } from './shell/composer';
import { JobBanner, JobStatusShort } from './shell/job-banner';
import { DEFAULT_LANGUAGE, type CardPick, type View } from './shell/shell-config';

/** The language the pair answer asked for, until the user picks one. */
export function Workspace() {
  const session = useSession();
  const [picked, setPicked] = useState<Language | null>(null);
  const language = picked ?? session.uiLanguage ?? DEFAULT_LANGUAGE;

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <LocaleProvider language={language} setLanguage={setPicked}>
      <VisualViewportProvider>
        <WorkspaceBody session={session} />
      </VisualViewportProvider>
    </LocaleProvider>
  );
}

/**
 * The runtime answers with the display name, and it needs a session, so this
 * reads only after the pairing or the cookie has settled.
 */
function BrandName() {
  const { language } = useLocale();
  const brand = useBrand();
  if (brand.brand === null) {
    return null;
  }
  return <>{language === 'ko' ? brand.brand.display_name_ko : brand.brand.display_name_en}</>;
}

function WorkspaceBody({ session }: { session: SessionResult }) {
  const { t, language } = useLocale();
  const [view, setView] = useState<View>('first');
  const [jobId, setJobId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [card, setCard] = useState<CardPick | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionErrorKey, setActionErrorKey] = useState<string | null>(null);
  const job = useJob(jobId);

  /**
   * One sentence starts a video: a project holds it, the video is the unit the
   * screens read, and the draft job fills the concept from the sentence.
   */
  const startFromSentence = async () => {
    const message = draft.trim();
    if (message === '' || submitting) {
      return;
    }
    setSubmitting(true);
    setActionErrorKey(null);
    try {
      const project = await createProject({ language });
      const created = await createVideo(project.id);
      const started = await submitDraft(created.id, {
        base_revision: created.revision,
        message,
        card_id: card?.id ?? null,
      });
      setJobId(started.id);
      setDraft('');
      setCard(null);
      setView('concept');
    } catch (error) {
      setActionErrorKey(messageKeyOf(error));
    } finally {
      setSubmitting(false);
    }
  };

  const openNewVideo = () => {
    setView('first');
    setJobId(null);
    setDraft('');
    setCard(null);
    setActionErrorKey(null);
  };

  const header = (
    <div className="flex flex-col">
      {session.state === 'pending' ? (
        <Notice tone="info" message={t('shell.session.connecting')} />
      ) : null}
      {session.state === 'missing' ? (
        <Notice tone="error" message={t('shell.session.missing')} />
      ) : null}
      {session.state === 'failed' && session.errorKey !== null ? (
        <Notice tone="error" message={t(`errors.${session.errorKey}`)} />
      ) : null}
      {actionErrorKey === null ? null : (
        <Notice
          tone="error"
          message={t(`errors.${actionErrorKey}`)}
          onDismiss={() => setActionErrorKey(null)}
          dismissLabel={t('shell.notice.dismiss')}
        />
      )}
      {job.failureKey === null ? null : (
        <Notice tone="error" message={t(`errors.${job.failureKey}`)} />
      )}
      {job.job === null ? null : <JobBanner job={job.job} />}
    </div>
  );

  return (
    <AppShell
      view={view}
      brand={session.state === 'ready' ? <BrandName /> : null}
      onNewVideo={openNewVideo}
      onStage={setView}
      header={header}
      jobStatus={job.job === null ? null : <JobStatusShort job={job.job} />}
      composer={
        view === 'first' ? null : (
          <PlaceholderComposer
            label={t('shell.stage.composerPlaceholder')}
            placeholder={t('shell.stage.composerPlaceholder')}
            sendLabel={t('shell.first.send')}
            reason={t('shell.stage.composerReason')}
          />
        )
      }
    >
      {view === 'first' ? (
        <FirstScreen
          draft={draft}
          card={card}
          submitting={submitting}
          ready={session.state === 'ready'}
          onDraftChange={setDraft}
          onPickCard={setCard}
          onClearCard={() => setCard(null)}
          onSubmit={() => void startFromSentence()}
        />
      ) : view === 'concept' ? (
        <ConceptRoute />
      ) : view === 'script' ? (
        <ScriptRoute />
      ) : view === 'edit' ? (
        <EditRoute />
      ) : (
        <ExportRoute />
      )}
    </AppShell>
  );
}
