// Shared motion vocabulary: one curve family, short durations, transform + opacity only.
// Enter with EASE_OUT, move on screen with EASE_IN_OUT, physical things (drawers, indicators) spring.
import type { Transition, Variants } from "motion/react";

export const EASE_OUT = [0.23, 1, 0.32, 1] as const;
export const EASE_IN_OUT = [0.77, 0, 0.175, 1] as const;
export const EASE_DRAWER = [0.32, 0.72, 0, 1] as const;

/** Sidebar indicator, segmented thumbs, sheets: quick, no visible bounce. */
export const SPRING: Transition = { type: "spring", stiffness: 420, damping: 36, mass: 0.9 };
/** Press feedback on the one hero action (Approve). */
export const PRESS_SPRING: Transition = { type: "spring", stiffness: 600, damping: 30 };

export const fadeUp: Variants = {
  hidden: { opacity: 0, transform: "translateY(6px)" },
  show: { opacity: 1, transform: "translateY(0px)", transition: { duration: 0.26, ease: EASE_OUT } },
};

/** Parent that cascades its children on first appearance (45ms apart). Never used on refreshes. */
export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.045, delayChildren: 0.02 } },
};

export const rowLayout: Transition = { duration: 0.2, ease: EASE_OUT };
