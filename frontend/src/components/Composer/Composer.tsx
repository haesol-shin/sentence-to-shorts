import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import { Plus } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './Composer.css';

import { IconButton } from '../IconButton/IconButton';
import { SendButton } from '../SendButton/SendButton';
import { statesOf, type ForceState } from '../force-state';

export type ComposerProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value' | 'defaultValue'> & {
  /** The accessible name of the text field. */
  label: string;
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  onSend?: () => void;
  sendLabel?: string;
  loading?: boolean;
  disabled?: boolean;
  /** Shows the rounded dashed file drop state on the box itself. */
  dropActive?: boolean;
  /** Attachment chips that sit above the text, for example file chips. */
  attachments?: ReactNode;
  /** Value chips that sit in the button row, for example language and length. */
  chips?: ReactNode;
  /** Adds a library icon button. Hidden when false. */
  attachLabel?: string;
  onAttach?: () => void;
  forceState?: ForceState;
};



/**
 * The one composer for the first screen and the chat column. It grows upward
 * to ten lines, then scrolls inside with a top fade. The send circle stays 32
 * and its transparent ring fills 44.
 */
export function Composer({
  label,
  value,
  defaultValue = '',
  onValueChange,
  onSend,
  sendLabel = '보내기',
  loading = false,
  disabled = false,
  dropActive = false,
  attachments,
  chips,
  attachLabel,
  onAttach,
  forceState,
  className,
  placeholder,
  ...rest
}: ComposerProps) {
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');
  const [inner, setInner] = useState(defaultValue);
  const [overflowing, setOverflowing] = useState(false);
  const field = useRef<HTMLTextAreaElement | null>(null);
  const text = value ?? inner;

  useEffect(() => {
    const element = field.current;
    if (element === null) return;
    const measure = () => {
      element.style.height = 'auto';
      const max = Number.parseFloat(getComputedStyle(element).maxHeight);
      const next = Number.isFinite(max) ? Math.min(element.scrollHeight, max) : element.scrollHeight;
      if (next > 0) element.style.height = `${next}px`;
      if (element.scrollHeight > element.clientHeight + 1) {
        element.scrollTop = element.scrollHeight;
      }
      setOverflowing(element.scrollHeight > element.clientHeight + 1);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);

  return (
    <div
      className={cn('composer', className)}
      data-drop={dropActive ? '' : undefined}
      data-overflow={overflowing ? '' : undefined}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
    >
      {attachments === undefined ? null : <div className="composer__attachments">{attachments}</div>}
      <div className="composer__field">
        <textarea
          {...rest}
          ref={field}
          className="composer__input"
          aria-label={label}
          placeholder={placeholder}
          value={text}
          disabled={isDisabled}
          rows={1}
          onChange={(event) => {
            if (value === undefined) setInner(event.target.value);
            onValueChange?.(event.target.value);
          }}
        />
      </div>
      <div className="composer__row">
        {attachLabel === undefined ? null : (
          <IconButton label={attachLabel} onClick={onAttach} disabled={isDisabled}>
            <Plus aria-hidden="true" />
          </IconButton>
        )}
        {chips === undefined ? null : <div className="composer__chips">{chips}</div>}
        <div className="composer__send">
          <SendButton
            label={sendLabel}
            loading={loading}
            disabled={isDisabled}
            onClick={onSend}
          />
        </div>
      </div>
    </div>
  );
}
