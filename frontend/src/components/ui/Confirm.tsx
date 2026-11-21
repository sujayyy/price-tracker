import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

interface ConfirmOptions {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (o: ConfirmOptions) => Promise<boolean>;
const Ctx = createContext<ConfirmFn>(async () => false);

/** `const confirm = useConfirm(); if (await confirm({...})) …` — an accessible modal instead of window.confirm. */
export const useConfirm = () => useContext(Ctx);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const ref = useRef<HTMLDialogElement>(null);
  const confirm = useCallback<ConfirmFn>((o) => new Promise((resolve) => setState({ ...o, resolve })), []);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (state && !d.open) d.showModal();
    if (!state && d.open) d.close();
  }, [state]);

  function finish(v: boolean) {
    state?.resolve(v);
    setState(null);
  }

  return (
    <Ctx.Provider value={confirm}>
      {children}
      <dialog
        ref={ref}
        className="confirm-dialog"
        aria-labelledby="confirm-title"
        onCancel={(e) => {
          e.preventDefault();
          finish(false);
        }}
      >
        {state && (
          <div className="w-[min(440px,calc(100vw-32px))]">
            <div className="p-6">
              {state.danger && (
                <span className="mb-4 grid h-9 w-9 place-items-center rounded-full bg-bad/10 text-bad" aria-hidden>
                  <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></svg>
                </span>
              )}
              <h2 id="confirm-title" className="text-[16px] font-semibold tracking-[-0.015em]">{state.title}</h2>
              {state.body && <div className="mt-2 text-[13px] leading-relaxed text-muted">{state.body}</div>}
            </div>
            <div className="flex justify-end gap-2 border-t border-line bg-sunken/50 px-6 py-3.5">
              <button className="btn-ghost" onClick={() => finish(false)}>Cancel</button>
              <button className={state.danger ? "btn border border-bad bg-bad text-white hover:bg-bad/90" : "btn-primary"} onClick={() => finish(true)} autoFocus>
                {state.confirmLabel ?? "Confirm"}
              </button>
            </div>
          </div>
        )}
      </dialog>
    </Ctx.Provider>
  );
}
