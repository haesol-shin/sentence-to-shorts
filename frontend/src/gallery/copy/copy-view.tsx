import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';

import { Button } from '@/components/Button/Button';
import { TextField } from '@/components/TextField/TextField';

import { GalleryTop } from '../gallery-top';
import { checkCopy, errorLine, type CopyError } from './checks';
import { parseCopyIndex, type CopyFileIndex, type CopyIndex, type CopyPreview } from './model';
import { saveCopy } from './save';
import './copy.css';

type Draft = { ko: string; en: string };

const LABELS: Record<string, string> = {
  shell: '공통·첫 화면',
  concept: '컨셉',
  script: '대본',
  edit: '편집',
  export: '내보내기',
  audio: '소리',
  errors: '오류 안내',
};

function draftId(namespace: string, key: string): string {
  return `${namespace}\u0000${key}`;
}

function cloneFiles(files: readonly CopyFileIndex[]): CopyFileIndex[] {
  return files.map((file) => ({ ...file, entries: file.entries.map((entry) => ({ ...entry })) }));
}

function CopyEditor({
  draft,
  originalKo,
  originalEn,
  errors,
  dirty,
  editable,
  saving,
  notice,
  onChange,
  onSave,
  onRevert,
  onCancel,
}: {
  draft: Draft;
  originalKo: string;
  originalEn: string;
  errors: readonly CopyError[];
  dirty: boolean;
  editable: boolean;
  saving: boolean;
  notice: string | null;
  onChange: (field: 'ko' | 'en', value: string) => void;
  onSave: () => void;
  onRevert: () => void;
  onCancel: () => void;
}): ReactNode {
  const blocked = errors.length > 0;
  const failed = blocked || (notice !== null && notice !== '저장했어요');
  return (
    <div className="copy-editor">
      <label className="copy-editor__field">
        <span>한국어</span>
        <textarea
          value={draft.ko}
          readOnly={!editable || saving}
          rows={3}
          onChange={(event) => onChange('ko', event.target.value)}
          aria-label="한국어 문구"
        />
      </label>
      <label className="copy-editor__field">
        <span>영어</span>
        <textarea
          value={draft.en}
          readOnly={!editable || saving}
          rows={3}
          onChange={(event) => onChange('en', event.target.value)}
          aria-label="영어 문구"
        />
      </label>
      <div className="copy-editor__bar">
        <p className={failed ? 'copy-editor__error' : 'copy-editor__ok'} role="status">
          {notice ?? errorLine(errors)}
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={onRevert}
          disabled={!dirty || saving}
        >
          되돌리기
        </Button>
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={saving}>
          취소
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={onSave}
          disabled={!editable || !dirty || blocked || saving}
        >
          {saving ? '저장 중' : '저장'}
        </Button>
      </div>
      {editable ? null : (
        <p className="copy-editor__readonly">
          이 갤러리는 읽기 전용이에요. 문구를 고치려면 <code>npm run copy</code>로 연 갤러리에서
          저장해요.
        </p>
      )}
      <p className="copy-editor__original">
        원래 값: {originalKo} / {originalEn}
      </p>
    </div>
  );
}

function PreviewFrame({
  frameRef,
  label,
}: {
  frameRef: RefObject<HTMLIFrameElement>;
  label: string;
}): ReactNode {
  return (
    <div className="copy-preview" data-copy-preview-case={label}>
      <iframe ref={frameRef} title={`문구 미리보기 ${label}`} src={`?copy=1&case=${encodeURIComponent(label)}`} />
    </div>
  );
}

function CopyScreen({
  index,
  initialFile,
}: {
  index: CopyIndex;
  initialFile: string | null;
}): ReactNode {
  const first = index.files.find((file) => file.namespace === initialFile) ?? index.files[0];
  const [namespace, setNamespace] = useState(first.namespace);
  const [files, setFiles] = useState<CopyFileIndex[]>(() => cloneFiles(index.files));
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewChoice, setPreviewChoice] = useState<string | null>(null);
  const [previewLanguage, setPreviewLanguage] = useState<'ko' | 'en'>('ko');
  const frameRef = useRef<HTMLIFrameElement>(null);
  const editable = index.editable;

  const file = files.find((candidate) => candidate.namespace === namespace) ?? files[0];
  const entryMap = useMemo(
    () => new Map(file.entries.map((entry) => [entry.key, entry])),
    [file],
  );
  const needle = search.trim().toLowerCase();
  const rows =
    needle === ''
      ? file.entries
      : file.entries.filter(
          (entry) =>
            entry.key.toLowerCase().includes(needle) ||
            entry.ko.toLowerCase().includes(needle) ||
            entry.en.toLowerCase().includes(needle),
        );

  const selected = selectedKey === null ? undefined : entryMap.get(selectedKey);
  const originalKo = selected?.ko ?? '';
  const originalEn = selected?.en ?? '';
  const activeDraft =
    selectedKey === null
      ? null
      : (drafts[draftId(namespace, selectedKey)] ?? { ko: originalKo, en: originalEn });
  const dirty =
    activeDraft !== null && (activeDraft.ko !== originalKo || activeDraft.en !== originalEn);
  const errors =
    activeDraft === null
      ? []
      : checkCopy({
          originalKo,
          originalEn,
          ko: activeDraft.ko,
          en: activeDraft.en,
          koKeys: file.koKeys,
          enKeys: file.enKeys,
        });

  useEffect(() => {
    if (selectedKey === null) return;
    const row = [...document.querySelectorAll<HTMLElement>('[data-key]')].find(
      (node) => node.dataset.key === selectedKey,
    );
    row?.scrollIntoView({ block: 'nearest' });
  }, [selectedKey]);

  const chosenCase =
    selected?.cases.find((item) => item.label === previewChoice) ?? selected?.cases[0];
  const previewLabel = chosenCase?.label ?? null;
  const draftKo = activeDraft?.ko ?? '';
  const draftEn = activeDraft?.en ?? '';
  useEffect(() => {
    if (selectedKey === null || previewLabel === null) return undefined;
    const frame = frameRef.current;
    if (frame === null) return undefined;
    const preview: CopyPreview = {
      key: `${namespace}.${selectedKey}`,
      ko: draftKo,
      en: draftEn,
      language: previewLanguage,
    };
    const send = () => {
      frame.contentWindow?.postMessage(
        { type: 'gallery-copy-preview', preview },
        window.location.origin,
      );
    };
    frame.addEventListener('load', send);
    send();
    return () => frame.removeEventListener('load', send);
  }, [namespace, selectedKey, previewLabel, draftKo, draftEn, previewLanguage]);

  const chooseFile = (next: string) => {
    if (saving) return;
    setNamespace(next);
    setSelectedKey(null);
    setPreviewChoice(null);
    setNotice(null);
  };

  const chooseKey = (key: string) => {
    if (saving) return;
    setSelectedKey(key);
    setPreviewChoice(null);
    setNotice(null);
  };

  const changeDraft = (field: 'ko' | 'en', value: string) => {
    if (selectedKey === null || saving) return;
    const id = draftId(namespace, selectedKey);
    setDrafts((previous) => ({
      ...previous,
      [id]: { ...(previous[id] ?? { ko: originalKo, en: originalEn }), [field]: value },
    }));
    setNotice(null);
  };

  const revert = () => {
    if (selectedKey === null || saving) return;
    setDrafts((previous) => {
      const next = { ...previous };
      delete next[draftId(namespace, selectedKey)];
      return next;
    });
    setNotice(null);
  };

  const cancel = () => {
    if (saving) return;
    revert();
    setSelectedKey(null);
    setPreviewChoice(null);
    setNotice(null);
  };

  const commit = async () => {
    if (
      !editable ||
      selectedKey === null ||
      activeDraft === null ||
      saving ||
      errors.length > 0 ||
      !dirty
    ) {
      return;
    }
    const submitted = { ...activeDraft };
    const key = selectedKey;
    setSaving(true);
    setNotice(null);
    try {
      const result = await saveCopy({
        namespace,
        key,
        ko: submitted.ko,
        en: submitted.en,
        baseKo: originalKo,
        baseEn: originalEn,
        baseHashKo: file.koHash,
        baseHashEn: file.enHash,
      });
      if (!result.ok) {
        if (
          result.ko !== undefined &&
          result.en !== undefined &&
          result.koHash !== undefined &&
          result.enHash !== undefined
        ) {
          const nextKo = result.ko;
          const nextEn = result.en;
          const nextKoHash = result.koHash;
          const nextEnHash = result.enHash;
          setFiles((previous) =>
            previous.map((candidate) =>
              candidate.namespace !== namespace
                ? candidate
                : {
                    ...candidate,
                    koHash: nextKoHash,
                    enHash: nextEnHash,
                    entries: candidate.entries.map((entry) =>
                      entry.key === key ? { ...entry, ko: nextKo, en: nextEn } : entry,
                    ),
                  },
            ),
          );
          setDrafts((previous) => {
            const next = { ...previous };
            delete next[draftId(namespace, key)];
            return next;
          });
        }
        setNotice(errorLine(result.errors));
        return;
      }
      setFiles((previous) =>
        previous.map((candidate) =>
          candidate.namespace !== namespace
            ? candidate
            : {
                ...candidate,
                koHash: result.koHash,
                enHash: result.enHash,
                entries: candidate.entries.map((entry) =>
                  entry.key === key ? { ...entry, ko: result.ko, en: result.en } : entry,
                ),
              },
        ),
      );
      setDrafts((previous) => {
        const next = { ...previous };
        delete next[draftId(namespace, key)];
        return next;
      });
      setNotice('저장했어요');
    } catch {
      setNotice('연결을 확인하지 못했어요. 다시 시도해 주세요.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="copy-page">
      <GalleryTop tab="copy" />
      <p className="copy-page__hint">
        {editable
          ? '고친 문구는 저장 전에도 오른쪽 화면 사례 안에서 바로 보여요. 저장하면 한국어와 영어 파일이 함께 바뀌어요.'
          : '이 갤러리는 읽기 전용이에요. 문구를 고치려면 npm run copy로 연 갤러리에서 저장해요.'}
      </p>
      <div className="copy-page__body">
        <nav className="copy-files" aria-label="문구 파일">
          <h2>문구 파일</h2>
          {files.map((candidate) => (
            <button
              key={candidate.namespace}
              type="button"
              onClick={() => chooseFile(candidate.namespace)}
              disabled={saving}
              aria-current={candidate.namespace === namespace ? 'page' : undefined}
            >
              <span>{LABELS[candidate.namespace] ?? candidate.namespace}</span>
              <small>{candidate.koKeys.length}</small>
            </button>
          ))}
        </nav>

        <section className="copy-list" aria-label="문구 목록">
          <header className="copy-list__head">
            <h2>
              {LABELS[file.namespace] ?? file.namespace} 문구 {file.koKeys.length}개
            </h2>
            <TextField
              label="검색"
              value={search}
              placeholder="문구나 키 검색"
              className="copy-list__search"
              onChange={(event) => setSearch(event.target.value)}
            />
          </header>
          {rows.length === 0 ? (
            <p className="copy-list__empty">찾는 문구가 없어요.</p>
          ) : (
            <ul className="copy-rows">
              {rows.map((entry) => {
                const isSelected = entry.key === selectedKey;
                return (
                  <li
                    key={entry.key}
                    className={isSelected ? 'copy-row copy-row--selected' : 'copy-row'}
                    data-key={entry.key}
                  >
                    <button
                      type="button"
                      className="copy-row__select"
                      aria-expanded={isSelected}
                      disabled={saving}
                      onClick={() => chooseKey(entry.key)}
                    >
                      <code className="copy-row__key">{entry.key}</code>
                      <span className="copy-row__value">{entry.ko}</span>
                    </button>
                    {isSelected && activeDraft !== null ? (
                      <CopyEditor
                        draft={activeDraft}
                        originalKo={originalKo}
                        originalEn={originalEn}
                        errors={errors}
                        dirty={dirty}
                        editable={editable}
                        saving={saving}
                        notice={notice}
                        onChange={changeDraft}
                        onSave={() => {
                          void commit();
                        }}
                        onRevert={revert}
                        onCancel={cancel}
                      />
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <aside className="copy-side" aria-label="이 문구를 쓰는 곳">
          <h2>이 문구를 쓰는 곳</h2>
          {selected === undefined ? (
            <p className="copy-side__empty">왼쪽에서 문구를 고르면 쓰는 화면을 보여 줘요.</p>
          ) : (
            <>
              <p className="copy-side__key">
                <code>
                  {namespace}.{selected.key}
                </code>
              </p>
              {chosenCase === undefined || previewLabel === null ? (
                <p className="copy-side__empty">이 문구를 그리는 화면 사례가 없어요.</p>
              ) : (
                <>
                  <h3>보이는 화면</h3>
                  <p className="copy-side__case">
                    {chosenCase.title} · {chosenCase.label}
                  </p>
                  <div className="copy-preview__language" role="group" aria-label="미리보기 언어">
                    <Button
                      variant={previewLanguage === 'ko' ? 'primary' : 'secondary'}
                      size="sm"
                      aria-pressed={previewLanguage === 'ko'}
                      onClick={() => setPreviewLanguage('ko')}
                    >
                      한국어
                    </Button>
                    <Button
                      variant={previewLanguage === 'en' ? 'primary' : 'secondary'}
                      size="sm"
                      aria-pressed={previewLanguage === 'en'}
                      onClick={() => setPreviewLanguage('en')}
                    >
                      English
                    </Button>
                  </div>
                  <PreviewFrame frameRef={frameRef} label={previewLabel} />
                  <ul className="copy-matches">
                    {selected.cases.map((item) => (
                      <li key={item.label}>
                        <button
                          type="button"
                          aria-pressed={item.label === previewLabel}
                          onClick={() => setPreviewChoice(item.label)}
                        >
                          <span>{item.title}</span>
                          <small>{item.label}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <a
                    className="copy-go"
                    href={`?copy=1&case=${encodeURIComponent(previewLabel)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    화면 사례로 이동
                  </a>
                </>
              )}
              <h3>쓰는 파일</h3>
              {selected.usages.length === 0 ? (
                <p className="copy-side__empty">이 문구를 쓰는 코드가 없어요.</p>
              ) : (
                <ul className="copy-usages">
                  {selected.usages.map((usage) => (
                    <li key={`${usage.path}:${usage.line}`}>
                      <code>
                        {usage.path}:{usage.line}
                      </code>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

let indexPromise: Promise<CopyIndex> | null = null;

/** One request per page load, so React StrictMode's double effect does not build twice. */
function requestIndex(): Promise<CopyIndex> {
  if (indexPromise !== null) return indexPromise;
  const load = import.meta.env.DEV
    ? fetch('/__copy/index', { headers: { Accept: 'application/json' } }).then(
        async (response) => {
          if (!response.ok) throw new Error(String(response.status));
          return (await response.json()) as unknown;
        },
      )
    : import('virtual:copy-index').then((module) => module.default as unknown);
  indexPromise = load
    .then((value) => {
      const parsed = parseCopyIndex(value);
      if (parsed === null) throw new Error('bad index');
      return parsed;
    })
    .catch((error: unknown) => {
      indexPromise = null;
      throw error;
    });
  return indexPromise;
}

export function CopyPage({ initialFile }: { initialFile: string | null }): ReactNode {
  const [index, setIndex] = useState<CopyIndex | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    requestIndex()
      .then((value) => {
        if (stopped) return;
        setIndex(value);
        setLoadError(null);
      })
      .catch(() => {
        if (!stopped) setLoadError('문구 목록을 불러오지 못했어요. 새로 고쳐 주세요.');
      });
    return () => {
      stopped = true;
    };
  }, []);

  if (loadError !== null) {
    return (
      <div className="copy-page">
        <GalleryTop tab="copy" />
        <p className="copy-page__error">{loadError}</p>
        <Button variant="secondary" onClick={() => window.location.reload()}>
          다시 열기
        </Button>
      </div>
    );
  }
  if (index === null) {
    return (
      <div className="copy-page">
        <GalleryTop tab="copy" />
        <p className="copy-page__hint">문구 목록을 불러오는 중이에요.</p>
      </div>
    );
  }
  if (index.files.length === 0) {
    return (
      <div className="copy-page">
        <GalleryTop tab="copy" />
        <p className="copy-page__error">문구 파일이 없어요.</p>
      </div>
    );
  }
  return <CopyScreen index={index} initialFile={initialFile} />;
}
