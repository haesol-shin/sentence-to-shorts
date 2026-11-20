import { Button } from '@/components/Button/Button';
import { Toast } from '@/components/Toast/Toast';

export type GalleryToastProps = {
  open: boolean;
  onUndo?: () => void;
};

/** The one gallery toast shown in the state list and opened by the keyboard probe. */
export function GalleryToast({ open, onUndo }: GalleryToastProps) {
  return (
    <Toast open={open}>
      <span className="demo-toast-action">
        대본을 저장했어요
        <Button variant="ghost" size="sm" onClick={onUndo}>
          되돌리기
        </Button>
      </span>
    </Toast>
  );
}
