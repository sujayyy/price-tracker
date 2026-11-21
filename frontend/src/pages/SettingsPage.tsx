import { motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { ApiError, getTeamSettings, resetTeamSettings, saveTeamSettings, sendTestEmail } from "../api/client";
import Icon, { type IconName } from "../components/Icon";
import { useConfirm } from "../components/ui/Confirm";
import { PageHeader, Skeleton } from "../components/ui/Primitives";
import type { TeamSettings } from "../types";
import { formatDateTime, loadReviewer, saveReviewer } from "../lib/format";
import { fadeUp, stagger } from "../lib/motion";
import { type ThemeChoice, useTheme } from "../lib/theme";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SECTIONS = [
  { id: "profile", label: "Profile" },
  { id: "recipients", label: "Alert recipients" },
  { id: "appearance", label: "Appearance" },
];

/** One settings topic: body, then a footer with context on the left and the action on the right. */
function SettingsCard({ id, title, description, children, footer }: { id: string; title: string; description: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <motion.section variants={fadeUp} id={id} aria-labelledby={`${id}-title`} className="card scroll-mt-6 overflow-hidden">
      <div className="space-y-4 p-5 sm:p-6">
        <div>
          <h2 id={`${id}-title`} className="section-title">{title}</h2>
          <p className="mt-1 max-w-xl text-[13px] text-muted">{description}</p>
        </div>
        {children}
      </div>
      {footer && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-sunken/50 px-5 py-3 sm:px-6">{footer}</div>}
    </motion.section>
  );
}

function ProfileCard() {
  const [name, setName] = useState(loadReviewer);
  const [saved, setSaved] = useState(loadReviewer);
  const dirty = name.trim() !== saved;
  function save() {
    saveReviewer(name.trim());
    setSaved(name.trim());
    toast.success("Profile saved");
  }
  return (
    <SettingsCard
      id="profile"
      title="Profile"
      description="Your name appears when you approve or reject a proposal and in each product's price log."
      footer={
        <>
          <span className="text-[12px] text-muted">Stored in this browser.</span>
          <button className="btn-primary btn-sm" onClick={save} disabled={!dirty}>Save</button>
        </>
      }
    >
      <div className="max-w-sm">
        <label className="label" htmlFor="profile-name">Name</label>
        <input id="profile-name" className="input" autoComplete="name" placeholder="e.g. Asha (Pricing)" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && dirty && save()} />
      </div>
    </SettingsCard>
  );
}

function RecipientsCard() {
  const [data, setData] = useState<TeamSettings | null>(null);
  const [emails, setEmails] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "reset" | null>(null);
  const confirm = useConfirm();

  useEffect(() => {
    getTeamSettings()
      .then((d) => {
        setData(d);
        setEmails(d.ops_alert_emails);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const pendingDraft = draft.split(/[\s,;]+/).map((e) => e.trim().toLowerCase()).filter(Boolean);
  const dirty = data != null && (emails.join(",") !== data.ops_alert_emails.join(",") || pendingDraft.length > 0);

  function addDraft(): string[] | null {
    const bad = pendingDraft.filter((e) => !EMAIL.test(e));
    if (bad.length) {
      setError(`"${bad[0]}" isn't a valid email address.`);
      return null;
    }
    const next = [...new Set([...emails, ...pendingDraft])];
    setEmails(next);
    setDraft("");
    setError(null);
    return next;
  }

  async function save() {
    const list = addDraft();
    if (!list) return;
    if (!list.length) {
      setError("Add at least one address: alerts need somewhere to go.");
      return;
    }
    setBusy("save");
    try {
      const d = await saveTeamSettings(list, loadReviewer() || "dashboard");
      setData(d);
      setEmails(d.ops_alert_emails);
      toast.success("Alert recipients saved", { description: `${d.ops_alert_emails.length} address${d.ops_alert_emails.length === 1 ? "" : "es"}` });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setError(null);
    try {
      const res = await sendTestEmail(loadReviewer() || "dashboard");
      toast.success("Test email sent", { description: res.sent_to.join(", ") });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    const ok = await confirm({
      title: "Reset to the .env default?",
      body: "Alerts will go to OPS_ALERT_EMAILS from infra/.env again, and the list saved here will be forgotten.",
      confirmLabel: "Reset",
    });
    if (!ok) return;
    setBusy("reset");
    try {
      const d = await resetTeamSettings();
      setData(d);
      setEmails(d.ops_alert_emails);
      toast("Using the .env default", { description: d.ops_alert_emails.join(", ") || "OPS_ALERT_EMAILS is empty" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <SettingsCard
      id="recipients"
      title="Alert recipients"
      description="Every competitor alert and approval request is emailed to these addresses. A product can add one extra recipient in its own settings."
      footer={
        <>
          <span className="text-[12px] text-muted">
            {data?.source === "dashboard"
              ? <>Saved here{data.updated_by ? ` by ${data.updated_by}` : ""}{data.updated_at ? ` · ${formatDateTime(data.updated_at)}` : ""}</>
              : data ? "Currently from infra/.env (OPS_ALERT_EMAILS)" : " "}
          </span>
          <div className="flex gap-2">
            {data?.source === "dashboard" && <button className="btn-quiet btn-sm" onClick={reset} disabled={!!busy}>Reset to .env</button>}
            <button className="btn-primary btn-sm" onClick={save} disabled={!dirty || !!busy}>{busy === "save" ? "Saving…" : "Save"}</button>
          </div>
        </>
      }
    >
      {!data && !error ? (
        <Skeleton className="h-24 max-w-lg" />
      ) : (
        <div className="max-w-lg space-y-3">
          <ul className="divide-y divide-line rounded-[8px] border border-line" aria-label="Recipients">
            {emails.map((e) => (
              <li key={e} className="flex items-center gap-3 px-3 py-2">
                <span className="grid h-7 w-7 place-items-center rounded-full bg-sunken text-[12px] font-semibold text-muted" aria-hidden>{e[0].toUpperCase()}</span>
                <span className="min-w-0 flex-1 truncate text-[13px]">{e}</span>
                <button className="icon-btn" aria-label={`Remove ${e}`} title="Remove" onClick={() => setEmails((xs) => xs.filter((x) => x !== e))}>
                  <Icon name="x" className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
            {emails.length === 0 && <li className="px-3 py-3 text-[13px] text-warn">No recipients: alerts won't be emailed.</li>}
          </ul>
          <div className="flex gap-2">
            <input
              className="input"
              type="email"
              aria-label="Add a recipient"
              placeholder="name@company.com"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addDraft();
                }
              }}
            />
            <button className="btn-ghost" onClick={() => addDraft()} disabled={!draft.trim()}><Icon name="plus" />Add</button>
          </div>
          {data && (
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-[13px]">
              <span className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${data.email_configured ? "bg-good" : "bg-warn-fill"}`} aria-hidden />
                {data.email_configured ? <>Sending from <span className="num">{data.sender}</span></> : <>Email isn't set up: add SMTP_USER and SMTP_APP_PASSWORD to infra/.env</>}
              </span>
              <button className="btn-ghost btn-sm" onClick={test} disabled={!!busy || !data.email_configured || dirty} title={dirty ? "Save first: the test goes to the saved list" : undefined}>
                <Icon name="mail" className="h-3.5 w-3.5" />{busy === "test" ? "Sending…" : "Send test email"}
              </button>
            </div>
          )}
          {error && <p role="alert" className="rounded-[7px] border border-bad/30 bg-bad/[0.05] px-3 py-2 text-[13px] text-bad">{error}</p>}
        </div>
      )}
    </SettingsCard>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: IconName; hint: string }[] = [
  { value: "light", label: "Light", icon: "sun", hint: "Always light" },
  { value: "dark", label: "Dark", icon: "moon", hint: "Always dark" },
  { value: "system", label: "System", icon: "monitor", hint: "Match this device" },
];

function AppearanceCard() {
  const [theme, setTheme] = useTheme();
  return (
    <SettingsCard id="appearance" title="Appearance" description="Applies to this browser. You can also switch it from the ⌘K menu.">
      <div role="radiogroup" aria-label="Theme" className="grid max-w-lg grid-cols-3 gap-2">
        {THEMES.map((t) => (
          <button
            key={t.value}
            role="radio"
            aria-checked={theme === t.value}
            onClick={() => setTheme(t.value)}
            className={`flex cursor-pointer flex-col items-start gap-2 rounded-[8px] border p-3 text-left transition-colors duration-150 ${
              theme === t.value ? "border-brand bg-brand/[0.05] ring-1 ring-brand" : "border-line hover:border-line-strong"
            }`}
          >
            <Icon name={t.icon} className={theme === t.value ? "text-ink" : "text-muted"} />
            <span>
              <span className="block text-[13px] font-medium">{t.label}</span>
              <span className="block text-[12px] text-muted">{t.hint}</span>
            </span>
          </button>
        ))}
      </div>
    </SettingsCard>
  );
}

export default function SettingsPage() {
  const [active, setActive] = useState("profile");
  useEffect(() => {
    // Highlight the first section currently in view.
    const visible = new Set<string>();
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => (e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id)));
        const first = SECTIONS.find((s) => visible.has(s.id));
        if (first) setActive(first.id);
      },
      { rootMargin: "0px 0px -55% 0px" },
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description="Your name for the price log, who gets competitor alerts, and how Price Tracker looks." />
      <div className="grid gap-6 lg:grid-cols-[180px_1fr]">
        <nav aria-label="Settings sections" className="hidden lg:block">
          <ul className="sticky top-8 space-y-0.5">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                    setActive(s.id);
                  }}
                  className={`block rounded-[7px] border-l-2 px-2.5 py-1.5 text-[13px] transition-colors duration-150 ${active === s.id ? "border-brand bg-raised font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`}
                >
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <motion.div className="min-w-0 space-y-5" variants={stagger} initial="hidden" animate="show">
          <ProfileCard />
          <RecipientsCard />
          <AppearanceCard />
        </motion.div>
      </div>
    </div>
  );
}
