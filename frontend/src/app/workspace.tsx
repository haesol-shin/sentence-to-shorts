import { useEffect, useRef, useState } from 'react';

import {
  createProject,
  createVideo,
  messageKeyOf,
  submitDraft,
  type Language,
} from '@/shared/api/client';
import { resetRememberedScene } from '@/features/edit/edit-context';
import { useBrand } from '@/features/runtime/use-brand';
import { LocaleProvider, useLocale } from '@/shared/lib/i18n/locale';
import { useSession, type SessionResult } from '@/shared/lib/session';
import { useJob } from '@/shared/lib/use-job';
import { VisualViewportProvider } from '@/shared/lib/visual-viewport';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Notice, type NoticeTone } from '@/components/Notice/Notice';

import { FirstScreen } from './first-screen';
import { ConceptRoute } from './routes/concept';
import { EditRoute } from './routes/edit';
import { ExportRoute } from './routes/export';
import { ScriptRoute } from './routes/script';
import { AppShell } from './shell/app-shell';
import { PlaceholderComposer } from './shell/composer';
import { JobAnnouncer, JobBanner, JobStatusShort } from './shell/job-banner';
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

/** One notice row above the stage; a dismissible one carries its own close control. */
function HeaderNotice({
  tone = 'neutral',
  onDismiss,
  dismissLabel,
  children,
}: {
  tone?: NoticeTone;
  onDismiss?: () => void;
  dismissLabel?: string;
  children: string;
}) {
  return (
    <div className="flex items-start gap-2 px-4 pb-2">
      <Notice tone={tone}>{children}</Notice>
      {onDismiss !== undefined && dismissLabel !== undefined ? (
        <CloseButton label={dismissLabel} onClick={onDismiss} />
      ) : null}
    </div>
  );
}

function WorkspaceBody({ session }: { session: SessionResult }) {
  const { t, language } = useLocale();
  const [view, setView] = useState<View>('first');
  const nextPreset = useRef<{ projectId: string; presetId: string } | null>(null);
  const [video, setVideo] = useState<{
    id: string;
    scriptSessionId: string;
    topic: string;
    script: string;
    language: Language;
  } | null>(null);
  const sessionSeq = useRef(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [card, setCard] = useState<CardPick | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionErrorKey, setActionErrorKey] = useState<string | null>(null);
  const job = useJob(jobId);
  const draftJob = job.job?.id === jobId ? job.job : null;
  const serverScriptVideoId = import.meta.env.VITE_API_MODE === 'mock' ? null : video?.id ?? null;
  const draftState = serverScriptVideoId === null
    ? 'ready'
    : draftJob?.state === 'succeeded'
      ? draftJob.result?.status === 'applied' ? 'ready' : 'failed'
      : draftJob?.state === 'failed' || draftJob?.state === 'cancelled' ? 'failed' : 'pending';

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
      const preset = nextPreset.current;
      const projectId = preset?.projectId ?? (await createProject({ language })).id;
      const created = await createVideo(projectId, preset?.presetId);
      const started = await submitDraft(created.id, {
        base_revision: created.revision,
        message,
        card_id: card?.id ?? null,
      });
      if (nextPreset.current === preset) nextPreset.current = null;
      setJobId(started.id);
      sessionSeq.current += 1;
      setVideo({
        id: created.id,
        scriptSessionId: `${created.id}#${sessionSeq.current}`,
        topic: message,
        script: message,
        language,
      });
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
    setVideo(null);
    setJobId(null);
    setDraft('');
    setCard(null);
    setActionErrorKey(null);
  };

  const openEditAfterScriptConfirm = () => {
    if (video !== null) resetRememberedScene(video.id);
    setView('edit');
  };

  const header = (
    <div className="flex flex-col">
      {session.state === 'pending' ? (
        <HeaderNotice>{t('shell.session.connecting')}</HeaderNotice>
      ) : null}
      {session.state === 'missing' ? (
        <HeaderNotice tone="error">{t('shell.session.missing')}</HeaderNotice>
      ) : null}
      {session.state === 'failed' && session.errorKey !== null ? (
        <HeaderNotice tone="error">{t(`errors.${session.errorKey}`)}</HeaderNotice>
      ) : null}
      {actionErrorKey === null ? null : (
        <HeaderNotice
          tone="error"
          onDismiss={() => setActionErrorKey(null)}
          dismissLabel={t('shell.notice.dismiss')}
        >
          {t(`errors.${actionErrorKey}`)}
        </HeaderNotice>
      )}
      {job.failureKey === null ? null : (
        <HeaderNotice tone="error">{t(`errors.${job.failureKey}`)}</HeaderNotice>
      )}
      {job.job === null ? null : <JobBanner job={job.job} />}
    </div>
  );

  return (
    <AppShell
      view={view}
      videoId={video?.id ?? null}
      brand={session.state === 'ready' ? <BrandName /> : null}
      onNewVideo={openNewVideo}
      onStage={setView}
      draftWaiting={draftJob === null ? jobId !== null : (
        draftJob.state === 'queued' || draftJob.state === 'running' || draftJob.state === 'cancelling'
      )}
      header={header}
      jobStatus={job.job === null ? null : <JobStatusShort job={job.job} />}
      announcer={<JobAnnouncer job={job.job} />}
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
        <ScriptRoute
          key={video?.scriptSessionId}
          videoId={video?.scriptSessionId ?? null}
          serverVideoId={serverScriptVideoId}
          draftState={draftState}
          topic={video?.topic ?? null}
          userScript={video?.script ?? null}
          language={video?.language ?? language}
          onNext={openEditAfterScriptConfirm}
        />
      ) : view === 'edit' ? (
        <EditRoute />
      ) : (
        <ExportRoute
          key={video?.id}
          videoId={video?.id ?? null}
          onStage={setView}
          onSavePreset={(preset) => {
            nextPreset.current = { projectId: preset.project_id, presetId: preset.id };
          }}
        />
      )}
    </AppShell>
  );
}
