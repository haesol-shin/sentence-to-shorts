import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type DragEvent,
} from 'react';
import {
  Check,
  ChevronDown,
  ChevronUp,
  GripVertical,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';

import type { Language } from '@/shared/api/client';
import { Button } from '@/components/Button/Button';
import { IconButton } from '@/components/IconButton/IconButton';
import { MenuButton } from '@/components/MenuButton/MenuButton';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import {
  addLine,
  applyRewrite,
  applyToneScene,
  confirmScript,
  deleteLine,
  dismissRewrite,
  dismissToneScene,
  editLine,
  ensureScript,
  moveLineTo,
  moveScene,
  moveSceneTo,
  rewriteScene,
  setLength,
  setRegister,
  setSceneCount,
  stopRewrite,
  undo,
  useScript,
  useScriptLoadFailed,
} from './store';
import {
  DURATIONS,
  estimateLineSeconds,
  getScriptSceneCounts,
  MAX_DISPLAY_CHARS,
  MAX_SCENE_LINES,
  REGISTERS,
  sceneSeconds,
  textLength,
} from './model';
import type { Register, ScriptDraftState, TargetDuration, ToneSceneReview } from './types';
import './script.css';

/** A dragged line carries its id under its own type, so a scene drop ignores it. */
const LINE_DRAG_TYPE = 'application/x-script-line';

/** Show the whole card under the pointer while its grip drags, not the grip alone. */
function setCardDragImage(event: DragEvent<HTMLElement>, selector: string): void {
  const card = event.currentTarget.closest(selector);
  if (card === null) {
    return;
  }
  const box = card.getBoundingClientRect();
  event.dataTransfer.setDragImage(card, event.clientX - box.left, event.clientY - box.top);
}

function LineBox({
  label,
  placeholder,
  value,
  disabled,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const node = useRef<HTMLTextAreaElement>(null);

  // The box grows with Enter-made lines only; a long line scrolls sideways.
  useLayoutEffect(() => {
    const textarea = node.current;
    if (textarea === null) {
      return;
    }
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={node}
      aria-label={label}
      placeholder={placeholder}
      value={value}
      rows={1}
      wrap="off"
      disabled={disabled}
      data-slot="script-line-input"
      onChange={(event) => onChange(event.target.value)}
      className="script-line-input"
    />
  );
}

/**
 * The script step: scene cards without pictures, a document head with length,
 * scene count and tone, and one step button at the bottom right. The screen
 * only writes Scene.lines; the conversation pane owns the chat answer, the
 * target chip and the tone decision buttons (exported from the store).
 */
export function ScriptScreen({
  videoId = null,
  serverVideoId = null,
  draftState = 'ready',
  topic = null,
  userScript = null,
  language = 'ko',
  onNext,
}: {
  videoId?: string | null;
  serverVideoId?: string | null;
  draftState?: ScriptDraftState;
  topic?: string | null;
  userScript?: string | null;
  /** The video's language; the interface language is not the session. */
  language?: Language;
  onNext?: () => void;
}) {
  const { t } = useLocale();
  const snapshot = useScript();
  const loadFailed = useScriptLoadFailed();
  const cardRefs = useRef(new Map<string, HTMLLIElement>());
  const noteId = useId();
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (draftState === 'ready') {
      void ensureScript(language, { id: videoId, topic, script: userScript }, serverVideoId);
    }
  }, [draftState, language, videoId, topic, userScript, serverVideoId]);

  // Undo by keyboard outside a text box; inside one, the box keeps its own typing history.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        (event.key !== 'z' && event.key !== 'Z') ||
        !(event.ctrlKey || event.metaKey) ||
        event.shiftKey ||
        event.altKey ||
        (target instanceof HTMLElement &&
          (target.isContentEditable || target.closest('input, textarea, select') !== null))
      ) {
        return;
      }
      event.preventDefault();
      undo();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const highlighted = snapshot?.highlightedSceneId ?? null;
  const focusToken = snapshot?.focusToken ?? 0;
  useEffect(() => {
    if (highlighted === null) {
      return;
    }
    cardRefs.current.get(highlighted)?.scrollIntoView?.({ block: 'nearest' });
  }, [highlighted, focusToken]);

  if (draftState !== 'ready' || snapshot === null ||
      (videoId !== null && snapshot.document.id !== videoId)) {
    return (
      <section
        data-slot="stage-panel"
        data-stage="script"
        aria-label={t('script.title')}
        className="script-screen script-screen--empty"
      >
        {draftState === 'failed' || (draftState === 'ready' && loadFailed) ? (
          <p role="alert" className="script-message">
            {t('script.error.load')}
          </p>
        ) : (
          <p role="status" className="script-message">
            {t('script.loading')}
          </p>
        )}
      </section>
    );
  }

  const script = snapshot.document;
  const confirmed = snapshot.confirmed;
  const confirming = snapshot.busy && snapshot.workingSceneId === null;
  const structureLocked =
    snapshot.busy || snapshot.rewrite !== null || snapshot.tone !== null;
  const toneLocked = snapshot.busy || snapshot.rewrite !== null;
  const rewriteBlocked =
    snapshot.busy || snapshot.rewrite !== null || snapshot.tone !== null;
  const toneValue = snapshot.tone?.to ?? script.register;
  const toneByScene = new Map<string, ToneSceneReview>(
    (snapshot.tone?.scenes ?? []).map((review) => [review.sceneId, review]),
  );
  const note =
    snapshot.error !== null
      ? t(snapshot.error)
      : confirmed
        ? t('script.confirm.done')
        : snapshot.nextBlockedReason !== null
          ? t(snapshot.nextBlockedReason)
          : null;

  // A confirmed script is confirmed again, so lines changed after the first confirmation go along too.
  const goNext = async () => {
    if (await confirmScript() && mounted.current) {
      onNext?.();
    }
  };

  const durationItems = DURATIONS.map((seconds) => ({
    value: String(seconds),
    label: t(`script.length.${seconds}`),
  }));
  const sceneItems = getScriptSceneCounts().map((count) => ({
    value: String(count),
    label: String(count),
  }));
  const toneItems = REGISTERS.map((register) => ({
    value: register,
    label: t(`script.tone.${register}`),
  }));

  return (
    <section
      data-slot="stage-panel"
      data-stage="script"
      aria-label={t('script.title')}
      className="script-screen"
    >
      <div data-slot="script-document" className="script-document">
        <ScrollPane label={t('script.document')} jumpLabel={t('shell.scroll.jump')} className="script-document-pane">
          <header className="script-head" data-slot="script-head">
            <div className="script-head-row">
              <h2>{t('script.title')}</h2>
              <div className="script-fields" data-slot="script-fields">
                <ValueField
                  label={t('script.field.length')}
                  name={t('script.field.length')}
                  display={t('script.length.display', {
                    seconds: snapshot.totalSeconds,
                    target: t(`script.length.${script.target_duration_s}`),
                  })}
                  items={durationItems}
                  value={String(script.target_duration_s)}
                  onValueChange={(value) => setLength(Number(value) as TargetDuration)}
                  disabled={structureLocked}
                />
                <ValueField
                  label={t('script.field.scenes')}
                  name={t('script.field.scenes')}
                  display={t('script.scenes.display', { count: script.scene_order.length })}
                  items={sceneItems}
                  value={String(script.scene_order.length)}
                  onValueChange={(value) => setSceneCount(Number(value))}
                  disabled={structureLocked}
                />
                <ValueField
                  className="script-tone-field"
                  label={t('script.field.tone')}
                  name={t('script.field.tone')}
                  display={t(`script.tone.name.${toneValue}`)}
                  items={toneItems}
                  value={toneValue}
                  onValueChange={(value) => setRegister(value as Register)}
                  disabled={toneLocked}
                />
              </div>
            </div>
            {snapshot.tone === null ? null : (
              <p className="script-tone-note" role="status">
                {t('script.tone.preview')}
              </p>
            )}
          </header>

          <ol className="script-scenes" data-slot="script-scenes">
            {script.scene_order.map((sceneId, index) => {
              const scene = script.scenes[sceneId];
              if (scene === undefined) {
                return null;
              }
              const number = index + 1;
              const working = snapshot.workingSceneId === sceneId;
              const review = snapshot.rewrite?.sceneId === sceneId ? snapshot.rewrite : null;
              const toneReview = toneByScene.get(sceneId) ?? null;
              return (
                <li
                  key={sceneId}
                  ref={(node) => {
                    if (node === null) {
                      cardRefs.current.delete(sceneId);
                    } else {
                      cardRefs.current.set(sceneId, node);
                    }
                  }}
                  data-slot="script-scene"
                  data-scene-id={sceneId}
                  data-changed={snapshot.changedSceneIds.includes(sceneId) ? 'true' : undefined}
                  data-highlighted={highlighted === sceneId ? 'true' : undefined}
                  className="script-scene"
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    if (structureLocked) {
                      return;
                    }
                    const moved = event.dataTransfer.getData('text/plain');
                    if (moved !== '') {
                      moveSceneTo(moved, index);
                    }
                  }}
                >
                  <div
                    className="script-card"
                    data-working={working ? 'true' : undefined}
                  >
                    <div className="script-card-head">
                      <button
                        type="button"
                        draggable={!structureLocked}
                        aria-label={t('script.scene.grip', { number })}
                        data-slot="script-grip"
                        className="script-grip hit-area focus-ring"
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = 'move';
                          event.dataTransfer.setData('text/plain', sceneId);
                          setCardDragImage(event, '.script-card');
                        }}
                      >
                        <GripVertical aria-hidden size={20} />
                      </button>
                      <span className="script-card-number">
                        {t('script.scene.label', { number })}
                      </span>
                      <span className="script-card-seconds" data-slot="script-scene-seconds">
                        {t('script.line.seconds', { seconds: sceneSeconds(script, sceneId) })}
                      </span>
                      {working ? (
                        <span data-slot="script-working" className="script-working">
                          <span aria-hidden className="spinner script-spinner" />
                          {t('script.working')}
                        </span>
                      ) : null}
                      {snapshot.changedSceneIds.includes(sceneId) ? (
                        <span data-slot="script-changed" className="script-changed">
                          <Check aria-hidden size={20} />
                          {t('script.changed')}
                        </span>
                      ) : null}
                      <div className="script-tools">
                        <IconButton
                          size="36"
                          label={t('script.scene.moveUp')}
                          disabled={structureLocked || index === 0}
                          onClick={() => moveScene(sceneId, -1)}
                        >
                          <ChevronUp aria-hidden size={20} />
                        </IconButton>
                        <IconButton
                          size="36"
                          label={t('script.scene.moveDown')}
                          disabled={structureLocked || index === script.scene_order.length - 1}
                          onClick={() => moveScene(sceneId, 1)}
                        >
                          <ChevronDown aria-hidden size={20} />
                        </IconButton>
                        <MenuButton
                          label={t('script.scene.menu', { number })}
                          trigger={
                            <IconButton
                              size="36"
                              label={t('script.scene.menu', { number })}
                              data-slot="script-scene-menu"
                              disabled={structureLocked}
                            >
                              <MoreHorizontal aria-hidden size={20} />
                            </IconButton>
                          }
                          items={[
                            {
                              value: 'rewrite',
                              label: t('script.rewrite'),
                              disabled: structureLocked || rewriteBlocked,
                            },
                            {
                              value: 'up',
                              label: t('script.scene.moveUp'),
                              disabled: structureLocked || index === 0,
                            },
                            {
                              value: 'down',
                              label: t('script.scene.moveDown'),
                              disabled: structureLocked || index === script.scene_order.length - 1,
                            },
                          ]}
                          onSelect={(value) => {
                            if (value === 'rewrite') {
                              void rewriteScene(sceneId);
                            } else {
                              moveScene(sceneId, value === 'up' ? -1 : 1);
                            }
                          }}
                        />
                      </div>
                    </div>

                    {review !== null ? (
                      <div
                        data-slot="script-review"
                        aria-label={t('script.review.title')}
                        className="script-review"
                      >
                        <ul className="script-review-lines" aria-label={t('script.tone.old')}>
                          {review.before.map((text, lineIndex) => (
                            <li key={`before-${lineIndex}`}>
                              <del>{text}</del>
                            </li>
                          ))}
                        </ul>
                        <ul
                          className="script-review-lines script-review-new"
                          aria-label={t('script.tone.new')}
                        >
                          {review.after.map((text, lineIndex) => (
                            <li key={`after-${lineIndex}`}>{text}</li>
                          ))}
                        </ul>
                        <div className="script-review-actions">
                          <Button
                            size="36"
                            variant="ghost"
                            iconStart={<X aria-hidden size={16} />}
                            onClick={dismissRewrite}
                          >
                            {t('script.review.keep')}
                          </Button>
                          <Button size="36" iconStart={<Check aria-hidden size={16} />} onClick={applyRewrite}>
                            {t('script.review.apply')}
                          </Button>
                        </div>
                      </div>
                    ) : toneReview !== null ? (
                      <div
                        data-slot="script-tone-preview"
                        aria-label={t('script.tone.label')}
                        className="script-review"
                      >
                        <ul className="script-review-lines" aria-label={t('script.tone.old')}>
                          {scene.lines.map((line) => {
                            const tone = toneReview.lines.find((entry) => entry.lineId === line.id);
                            return (
                              <li key={line.id}>{tone === undefined ? line.display_text : <del>{tone.before}</del>}</li>
                            );
                          })}
                        </ul>
                        <ul
                          className="script-review-lines script-review-new"
                          aria-label={t('script.tone.new')}
                        >
                          {toneReview.lines.map((line) => (
                            <li key={line.lineId}>{line.after}</li>
                          ))}
                        </ul>
                        <div className="script-review-actions">
                          <Button
                            size="36"
                            variant="ghost"
                            disabled={snapshot.busy}
                            iconStart={<X aria-hidden size={16} />}
                            onClick={() => dismissToneScene(sceneId)}
                          >
                            {t('script.review.keep')}
                          </Button>
                          <Button
                            size="36"
                            disabled={snapshot.busy}
                            iconStart={<Check aria-hidden size={16} />}
                            onClick={() => applyToneScene(sceneId)}
                          >
                            {t('script.review.apply')}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="script-lines">
                        {scene.lines.map((line, lineIndex) => (
                          <div
                            key={line.id}
                            data-slot="script-line"
                            className="script-line"
                            onDrop={(event) => {
                              const moved = event.dataTransfer.getData(LINE_DRAG_TYPE);
                              if (moved === '') {
                                return;
                              }
                              event.preventDefault();
                              event.stopPropagation();
                              if (!structureLocked) {
                                moveLineTo(sceneId, moved, lineIndex);
                              }
                            }}
                          >
                            <button
                              type="button"
                              draggable={!structureLocked && scene.lines.length > 1}
                              disabled={structureLocked || scene.lines.length < 2}
                              aria-label={t('script.line.grip', { scene: number, line: lineIndex + 1 })}
                              data-slot="script-line-grip"
                              className="script-grip script-line-grip hit-area focus-ring"
                              onDragStart={(event) => {
                                event.dataTransfer.effectAllowed = 'move';
                                event.dataTransfer.setData(LINE_DRAG_TYPE, line.id);
                                setCardDragImage(event, '.script-line');
                              }}
                            >
                              <GripVertical aria-hidden size={20} />
                            </button>
                            <div className="script-line-row">
                              <LineBox
                                label={t('script.line.label', {
                                  scene: number,
                                  line: lineIndex + 1,
                                })}
                                placeholder={t('script.line.placeholder')}
                                value={line.display_text}
                                disabled={confirming || working}
                                onChange={(text) => editLine(sceneId, line.id, text)}
                              />
                              {line.display_text.trim() === '' ? null : (
                                <span className="script-seconds" data-slot="script-line-seconds">
                                  {t('script.line.seconds', {
                                    seconds: estimateLineSeconds(line.display_text),
                                  })}
                                </span>
                              )}
                              <IconButton
                                size="36"
                                label={t('script.line.delete', { scene: number, line: lineIndex + 1 })}
                                data-slot="script-line-delete"
                                className="script-line-delete"
                                disabled={structureLocked || scene.lines.length < 2}
                                onClick={() => deleteLine(sceneId, line.id)}
                              >
                                <Trash2 aria-hidden size={20} />
                              </IconButton>
                            </div>
                            {textLength(line.display_text) > MAX_DISPLAY_CHARS ? (
                              <p
                                className="script-line-error"
                                data-slot="script-line-error"
                                role="alert"
                              >
                                {t('script.line.tooLong')}
                              </p>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}

                    {review === null && toneReview === null ? (
                      <div className="script-card-actions">
                        <Button
                          data-slot="script-rewrite"
                          size="36"
                          variant="secondary"
                          iconStart={<RefreshCw aria-hidden size={16} />}
                          running={working}
                          stopLabel={t('script.stop')}
                          onStop={stopRewrite}
                          disabled={!working && rewriteBlocked}
                          onClick={() => void rewriteScene(sceneId)}
                        >
                          {t('script.rewrite')}
                        </Button>
                        <Button
                          data-slot="script-add-line"
                          size="36"
                          variant="ghost"
                          iconStart={<Plus aria-hidden size={16} />}
                          disabled={
                            structureLocked ||
                            scene.lines.length >= MAX_SCENE_LINES
                          }
                          onClick={() => addLine(sceneId)}
                        >
                          {t('script.addLine')}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </ScrollPane>
      </div>

      <footer className="script-footer" data-slot="script-footer">
        {note === null ? null : (
          <p id={noteId} role="status" className="script-footer-note">
            {note}
          </p>
        )}
        <Button
          data-slot="script-next"
          disabled={
            snapshot.busy ||
            snapshot.nextBlockedReason !== null ||
            (confirmed && onNext === undefined)
          }
          aria-describedby={note === null ? undefined : noteId}
          onClick={() => void goNext()}
        >
          {t('script.next')}
        </Button>
      </footer>
    </section>
  );
}
