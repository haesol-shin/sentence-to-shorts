import { useEffect, useRef, useState } from 'react';

import {
  ApiProblemError,
  createProject,
  createVideo,
  messageKeyOf,
  submitDraft,
  type Language,
} from '@/shared/api/client';
import { attachConceptExtras, beginConcept, reloadConcept } from '@/features/concept/store';
import type { Attachment } from '@/features/concept/types';
import { resetRememberedScene } from '@/features/edit/edit-context';
import { useRuntimeHead } from '@/features/runtime/use-runtime-head';
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
  // The runtime answers with the display name and the key state, and it needs a
  // session, so this reads only after the pairing or the cookie has settled.
  const runtimeHead = useRuntimeHead(session.state === 'ready');
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
  const pendingExtras = useRef<Attachment[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  // The concept reload after a finished draft lands after the job state; the
  // first reply waits for it so it never reads the pre-draft defaults.
  const [draftRead, setDraftRead] = useState<'idle' | 'waiting' | 'done' | 'failed'>('idle');
  const [draft, setDraft] = useState('');
  const [card, setCard] = useState<CardPick | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionErrorKey, setActionErrorKey] = useState<string | null>(null);
  // When the profile uses the user's own key an `llm_auth` failure asks for the key again on the first screen; other profiles keep the header notice.
  const [authFailureKey, setAuthFailureKey] = useState<string | null>(null);
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
  const startFromSentence = async (
    attachments: Attachment[],
    options: { language: Language; duration: number },
  ) => {
    const message = draft.trim();
    if (message === '' || submitting) {
      return;
    }
    setSubmitting(true);
    setActionErrorKey(null);
    setAuthFailureKey(null);
    try {
      const preset = nextPreset.current;
      const projectId = preset?.projectId ?? (await createProject({ language: options.language })).id;
      const created = await createVideo(projectId, preset?.presetId);
      // The concept screen opens the video that exists now, with the texts the
      // draft should read; files and links wait until the draft has been written.
      const opened = await beginConcept({
        videoId: created.id,
        topic: message,
        cardId: card?.id ?? null,
        language: options.language,
        duration: options.duration,
        attachments: attachments.filter((attachment) => attachment.kind === 'text'),
      });
      pendingExtras.current = attachments.filter((attachment) => attachment.kind !== 'text');
      const started = await submitDraft(created.id, {
        base_revision: opened?.revision ?? created.revision,
        message,
        card_id: card?.id ?? null,
      });
      if (nextPreset.current === preset) nextPreset.current = null;
      setDraftRead('waiting');
      setJobId(started.id);
      sessionSeq.current += 1;
      setVideo({
        id: created.id,
        scriptSessionId: `${created.id}#${sessionSeq.current}`,
        topic: message,
        script: message,
        language: options.language,
      });
      setDraft('');
      setCard(null);
      setView('concept');
    } catch (error) {
      if (
        runtimeHead.llmKey.ownKey &&
        error instanceof ApiProblemError &&
        error.code === 'llm_auth_required'
      ) {
        setAuthFailureKey(error.messageKey);
      } else {
        setActionErrorKey(messageKeyOf(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const draftWritten = draftJob?.state === 'succeeded' ? draftJob.id : null;
  const draftApplied = draftJob?.result?.status === 'applied';
  const openVideoId = video?.id ?? null;
  // The draft job writes the concept values, so the screen reads the video
  // again before it starts the files and links held back at the start.
  useEffect(() => {
    if (draftWritten === null || openVideoId === null) return;
    const extras = pendingExtras.current;
    pendingExtras.current = [];
    let cancelled = false;
    void reloadConcept(openVideoId, draftApplied)
      .then((ok) => {
        if (!cancelled) setDraftRead(ok ? 'done' : 'failed');
      })
      .catch(() => {
        if (!cancelled) setDraftRead('failed');
      })
      .finally(() => {
        // The reply state is settled above; the held files and links start on
        // their own so a slow upload never keeps the first reply waiting.
        if (!cancelled) void attachConceptExtras(extras).catch(() => undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [draftApplied, draftWritten, openVideoId]);

  // The job started with no usable key: back to the first screen with the
  // sentence the user typed, so the key can be replaced and the sentence sent again.
  // Only where the key block renders; dev on the CLI and an unread runtime keep the job banner.
  const authFailed =
    runtimeHead.llmKey.ownKey && draftJob?.state === 'failed' && draftJob.error?.code === 'llm_auth';
  const typedSentence = video?.topic ?? null;
  useEffect(() => {
    if (!authFailed || typedSentence === null) return;
    setView('first');
    setVideo(null);
    setJobId(null);
    setDraft(typedSentence);
    setAuthFailureKey('error.llm_auth_required');
  }, [authFailed, typedSentence]);

  const openNewVideo = () => {
    setView('first');
    setVideo(null);
    setJobId(null);
    setDraftRead('idle');
    setDraft('');
    setCard(null);
    setActionErrorKey(null);
    setAuthFailureKey(null);
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
      {/* A finished job leaves the line to the announcer, so the faces keep their place under the top bar. */}
      {job.job === null || job.job.state === 'succeeded' ? null : <JobBanner job={job.job} />}
    </div>
  );

  return (
    <AppShell
      view={view}
      videoId={video?.id ?? null}
      sentence={video?.topic ?? null}
      brand={
        runtimeHead.brand === null
          ? null
          : language === 'ko'
            ? runtimeHead.brand.display_name_ko
            : runtimeHead.brand.display_name_en
      }
      onNewVideo={openNewVideo}
      onStage={setView}
      draftWaiting={draftJob === null ? jobId !== null : (
        draftJob.state === 'queued' || draftJob.state === 'running' || draftJob.state === 'cancelling' ||
        (draftJob.state === 'succeeded' && draftRead === 'waiting')
      )}
      header={header}
      jobStatus={job.job === null ? null : <JobStatusShort job={job.job} />}
      announcer={<JobAnnouncer job={job.job} />}
      composer={
        view === 'first' ? null : (
          <PlaceholderComposer
            label={t('shell.stage.composerPlaceholder')}
            placeholder={t('edit.composer.placeholder')}
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
          llmKey={runtimeHead.llmKey}
          authFailureKey={authFailureKey}
          onKeySaved={() => setAuthFailureKey(null)}
          onDraftChange={setDraft}
          onPickCard={setCard}
          onClearCard={() => setCard(null)}
          onSubmit={(_text, attachments, options) => void startFromSentence(attachments, options)}
        />
      ) : view === 'concept' ? (
        <ConceptRoute onNext={() => setView('script')} />
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
