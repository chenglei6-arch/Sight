import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
let modalStack: symbol[] = [];
export default function Modal({
  open = false,
  title = "",
  width = 560,
  onClose,
  children,
}: {
  open?: boolean;
  title?: string;
  width?: number;
  onClose: () => void;
  children?: ReactNode;
}) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const id = Symbol("modal");
    modalStack.push(id);
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && modalStack.at(-1) === id) {
        event.stopPropagation();
        close.current();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      modalStack = modalStack.filter((value) => value !== id);
      document.removeEventListener("keydown", keydown);
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal-card"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          <button
            className="btn btn-icon btn-sm"
            title="关闭 (Esc)"
            onClick={onClose}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
