"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export function WorkspaceDialog({
  open,
  onClose,
  title,
  id,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  id: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog
      ref={dialog}
      className={`workspace-dialog${wide ? " settings-drawer" : ""}`}
      aria-labelledby={`${id}-title`}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="dialog-header">
        <h2 id={`${id}-title`}>{title}</h2>
        <button
          type="button"
          className="dialog-close"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      {children}
    </dialog>
  );
}
