import { Fragment, type ReactNode } from 'react';

/**
 * A body line that holds two or more sentences. Each sentence starts on its
 * own line, so a reader sees the sentence edges; a single sentence stays as it
 * is. Locale strings keep their punctuation and never carry a newline.
 */
export function SentenceLines({ children }: { children: ReactNode }) {
  if (typeof children !== 'string') return <>{children}</>;
  const lines = children.split(/(?<=[.?!])\s+/u).filter((line) => line !== '');
  if (lines.length < 2) return <>{children}</>;

  return (
    <>
      {lines.map((line, index) => (
        <Fragment key={`${index}:${line}`}>
          {line}
          {index < lines.length - 1 ? (
            <>
              {' '}
              <br />
            </>
          ) : null}
        </Fragment>
      ))}
    </>
  );
}
