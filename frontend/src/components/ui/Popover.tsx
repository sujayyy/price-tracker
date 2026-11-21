import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { EASE_OUT } from "../../lib/motion";

/**
 * A small anchored menu. Opens below its trigger, scaling from the trigger's corner (origin-aware),
 * closes on outside click or Esc and returns focus to the trigger.
 */
export default function Popover({ trigger, children, align = "right", label }: {
  trigger: (props: { open: boolean; toggle: () => void; ref: React.Ref<HTMLButtonElement> }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => root.current && !root.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const close = () => setOpen(false);
  return (
    <div ref={root} className="relative">
      {trigger({ open, toggle: () => setOpen((o) => !o), ref: btn })}
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label={label}
            className={`absolute top-[calc(100%+8px)] z-40 w-[min(360px,calc(100vw-24px))] overflow-hidden rounded-[12px] border border-line bg-raised shadow-pop ${align === "right" ? "right-0 origin-top-right" : "left-0 origin-top-left"}`}
            initial={{ opacity: 0, transform: "scale(0.97)" }}
            animate={{ opacity: 1, transform: "scale(1)", transition: { duration: 0.15, ease: EASE_OUT } }}
            exit={{ opacity: 0, transform: "scale(0.97)", transition: { duration: 0.1, ease: EASE_OUT } }}
          >
            {children(close)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
