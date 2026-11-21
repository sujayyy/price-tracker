// Tells the header's approval badge to refresh after a proposal is created or resolved.
export const PROPOSALS_CHANGED = "price-tracker:proposals-changed";

export const notifyProposalsChanged = () => window.dispatchEvent(new Event(PROPOSALS_CHANGED));

// Your name changed in Settings: the sidebar profile follows.
export const REVIEWER_CHANGED = "price-tracker:reviewer-changed";
