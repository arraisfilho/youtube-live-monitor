import * as Dialog from "@radix-ui/react-dialog";
import { CheckCircle2, CircleAlert, LoaderCircle, X } from "lucide-react";
import { clsx } from "clsx";
import { t } from "../i18n";
import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode, type RefObject } from "react";
export function Button({
  className,
  variant = "primary",
  size = "standard",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
  size?: "standard" | "small" | "large" | "icon";
}) {
  return (
    <button
      className={clsx("button", `button-${variant}`, `button-${size}`, className)}
      {...props}
    />
  );
}
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={clsx("card", className)}>{children}</section>;
}
/** Disclosure menu on <details>: closes with Escape, an outside click or after choosing an item. */
export function ContextMenu({
  label,
  summaryClassName = "menu-trigger",
  summaryLabel,
  className,
  align = "end",
  children,
}: {
  label: ReactNode;
  summaryClassName?: string;
  summaryLabel?: string;
  className?: string;
  align?: "start" | "end";
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = (focusSummary = false) => {
    const details = ref.current;
    if (!details?.open) return;
    details.open = false;
    if (focusSummary) details.querySelector("summary")?.focus();
  };
  useEffect(() => {
    const dismiss = (event: Event) => {
      const details = ref.current;
      if (details?.open && event.target instanceof Node && !details.contains(event.target)) details.open = false;
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
    };
  }, []);
  return (
    <details
      ref={ref}
      className={clsx("context-menu", className)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && ref.current?.open) {
          event.preventDefault();
          close(true);
        }
      }}
    >
      <summary className={summaryClassName} aria-label={summaryLabel}>{label}</summary>
      <div
        className={clsx("menu", align === "start" && "menu-start")}
        onClick={(event) => {
          // The chosen item hides with the menu, so the focus goes back to the
          // trigger. A dialog opened by the item returns the focus there too.
          if ((event.target as HTMLElement).closest("button, a")) close(true);
        }}
      >
        {children}
      </div>
    </details>
  );
}
/** Where the focus was when a dialog opened: the control and the title of its card or page. */
export type FocusOrigin = { control: HTMLElement | null; heading: HTMLElement | null };
const TITLES = "h1, h2, h3";
/** Remembers the focused control as a dialog opens (the dialogs have no Dialog.Trigger). */
export function rememberFocus(): FocusOrigin {
  const active = document.activeElement as HTMLElement | null;
  const control = active && active !== document.body && typeof active.focus === "function" ? active : null;
  const area = control?.closest(".card, .list-section, section, article, main");
  return { control, heading: area?.querySelector<HTMLElement>(TITLES) ?? null };
}
/**
 * After a dialog closes, the control that opened it takes the focus back; when
 * it has left the page (a removed row, a deleted item), the title of
 * its card or the page <h1> does. It runs a frame later and only while nothing
 * holds the focus, so a navigation that focused the new page title keeps it.
 */
export function returnFocus(origin: FocusOrigin | null) {
  requestAnimationFrame(() => {
    const active = document.activeElement;
    if (active && active !== document.body) return;
    for (const target of [origin?.control, origin?.heading, document.querySelector<HTMLElement>("main h1")]) {
      if (!target?.isConnected) continue;
      if (target.matches(TITLES) && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus();
      if (document.activeElement === target) return;
    }
  });
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
  className = "",
  onClosed,
  initialFocus,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
  className?:string;
  /**
   * After the dialog left the page, when the rest of the page is no longer
   * hidden from assistive technology: the moment to show a success message.
   */
  onClosed?: () => void;
  /**
   * The field that takes the focus when the dialog opens, instead of the first
   * control (the close button). `autoFocus` would focus it before the opener is
   * remembered, and the focus could not go back to it.
   */
  initialFocus?: RefObject<HTMLElement | null>;
}) {
  const origin = useRef<FocusOrigin | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={clsx("dialog", wide && "dialog-wide", className)}
          onOpenAutoFocus={(event) => {
            origin.current = rememberFocus();
            const target = initialFocus?.current;
            if (!target) return;
            event.preventDefault();
            target.focus();
          }}
          onCloseAutoFocus={(event) => {
            // Without a trigger Radix would leave the focus on <body>.
            event.preventDefault();
            returnFocus(origin.current);
            origin.current = null;
            onClosed?.();
          }}
        >
          <div className="dialog-header">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              <Dialog.Description>{description}</Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" className="dialog-close" aria-label={t("Fechar janela")}>
                <X size={18} />
              </Button>
            </Dialog.Close>
          </div>
          <div className="dialog-body">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Confirmation before an action that removes or deletes: what happens is
 * explained in the dialog and the final button is filled red.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  busy = false,
  error,
  onClosed,
  cancelLabel,
  children,
  initialFocus,
  confirmVariant = "danger",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  /** See Modal: a field in `children` that takes the focus when the dialog opens. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** "primary" for a step that removes nothing (a password before turning something on). */
  confirmVariant?: "danger" | "primary";
  /** While the request runs, the dialog stays open and both buttons wait. */
  busy?: boolean;
  /**
   * Why the action failed. The dialog hides the rest of the page from
   * assistive technology, so the error is announced here, with the dialog open.
   */
  error?: string;
  /** See Modal: a success message shown here is announced once the page is back. */
  onClosed?: () => void;
  cancelLabel?: string;
  children?: ReactNode;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={(next) => !busy && onOpenChange(next)}
      title={title}
      description={description}
      onClosed={onClosed}
      initialFocus={initialFocus}
    >
      {children}
      <Notice tone="error">{error}</Notice>
      <div className="dialog-actions">
        <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
          {cancelLabel || t("Cancelar")}
        </Button>
        <Button
          variant={confirmVariant}
          className={confirmVariant === "danger" ? "button-confirm" : undefined}
          disabled={busy}
          onClick={onConfirm}
        >
          {busy && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/**
 * The result of an action next to the form that ran it. Success is a status;
 * an error is an alert that stays until it is dismissed. Render it with or
 * without a message: its live region exists before the message arrives, and
 * an empty notice takes no space. The dismiss button stays outside the region.
 */
export function Notice({
  tone = "success",
  children,
  onDismiss,
  id,
}: {
  tone?: "success" | "error";
  children?: ReactNode;
  onDismiss?: () => void;
  /** Of the message, for a field that points to its error (aria-describedby). */
  id?: string;
}) {
  const error = tone === "error";
  const shown = children != null && children !== false && children !== "";
  return (
    <div className={clsx("notice", error ? "is-error" : "is-success", !shown && "is-empty")}>
      {shown && (error ? <CircleAlert size={18} aria-hidden="true" /> : <CheckCircle2 size={18} aria-hidden="true" />)}
      <p role={error ? "alert" : "status"} aria-live={error ? "assertive" : "polite"} aria-atomic="true" id={id}>
        {shown ? children : null}
      </p>
      {shown && onDismiss && (
        <button type="button" className="notice-dismiss" aria-label={t("Dispensar mensagem")} onClick={onDismiss}>
          <X size={16} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
