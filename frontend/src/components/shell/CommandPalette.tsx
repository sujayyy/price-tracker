import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listProducts } from "../../api/client";
import type { Product } from "../../types";
import type { ThemeChoice } from "../../lib/theme";
import { formatInr, shortTitle } from "../../lib/format";
import Icon, { type IconName } from "../Icon";

const GROUP = "[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.06em] [&_[cmdk-group-heading]]:text-muted";
const ITEM = "flex h-10 cursor-pointer items-center gap-3 rounded-[8px] px-2.5 text-[13px] text-ink data-[selected=true]:bg-sunken";

// Opened with ⌘K / Ctrl+K many times a day, so it appears instantly: no animation by design.
export default function CommandPalette({ open, onOpenChange, setTheme }: { open: boolean; onOpenChange: (o: boolean) => void; setTheme: (t: ThemeChoice) => void }) {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) listProducts().then(setProducts).catch(() => {});
  }, [open]);

  function run(fn: () => void) {
    onOpenChange(false);
    fn();
  }

  const item = (icon: IconName, label: string, onSelect: () => void) => (
    <Command.Item onSelect={() => run(onSelect)} className={ITEM}>
      <Icon name={icon} className="text-muted" />
      <span className="flex-1 truncate">{label}</span>
    </Command.Item>
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command menu"
      overlayClassName="fixed inset-0 z-40 bg-gray-900/40"
      contentClassName="fixed left-1/2 top-[12vh] z-50 w-[min(600px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-[14px] border border-line bg-raised shadow-pop"
    >
      <div className="flex items-center gap-2.5 border-b border-line px-4">
        <Icon name="search" className="text-muted" />
        <Command.Input placeholder="Search products, SKUs, or jump to…" className="h-12 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint" />
        <kbd className="rounded-[4px] border border-line bg-sunken px-1.5 text-[11px] text-muted">esc</kbd>
      </div>
      <Command.List className="max-h-[min(360px,60vh)] overflow-y-auto p-1.5">
        <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted">No matches.</Command.Empty>
        <Command.Group heading="Go to" className={GROUP}>
          {item("overview", "Overview", () => navigate("/"))}
          {item("products", "Products", () => navigate("/products"))}
          {item("recommendations", "Recommendations", () => navigate("/recommendations"))}
          {item("inbox", "Approvals", () => navigate("/approvals"))}
          {item("monitoring", "Monitoring", () => navigate("/monitoring"))}
          {item("plus", "Add a product", () => navigate("/add"))}
          {item("settings", "Settings: profile, alert recipients, appearance", () => navigate("/settings"))}
        </Command.Group>
        {products.length > 0 && (
          <Command.Group heading="Products" className={GROUP}>
            {products.map((p) => (
              <Command.Item key={p.id} value={`${p.title} ${p.our_sku ?? ""} #${p.id}`} onSelect={() => run(() => navigate(`/products/${p.id}`))} className={ITEM}>
                <Icon name="package" className="text-muted" />
                <span className="min-w-0 flex-1 truncate">{shortTitle(p.title)}{p.our_sku && <span className="code ml-2 text-muted">{p.our_sku}</span>}</span>
                <span className="mono text-[12px] text-muted">{formatInr(p.our_price_inr)}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="Theme" className={GROUP}>
          {item("sun", "Light theme", () => setTheme("light"))}
          {item("moon", "Dark theme", () => setTheme("dark"))}
          {item("monitor", "Match system", () => setTheme("system"))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
