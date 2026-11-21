import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Toaster } from "sonner";
import { listProposals } from "./api/client";
import CommandPalette from "./components/shell/CommandPalette";
import Sidebar from "./components/shell/Sidebar";
import TopBar from "./components/shell/TopBar";
import { ConfirmProvider } from "./components/ui/Confirm";
import { Skeleton } from "./components/ui/Primitives";
import { PROPOSALS_CHANGED, REVIEWER_CHANGED } from "./lib/events";
import { loadReviewer } from "./lib/format";
import { EASE_OUT } from "./lib/motion";
import { useTheme } from "./lib/theme";

// Each page is its own chunk: the charting library only loads where a chart is shown.
const OverviewPage = lazy(() => import("./pages/DashboardPage"));
const ProductsPage = lazy(() => import("./pages/ProductsPage"));
const RecommendationsPage = lazy(() => import("./pages/RecommendationsPage"));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage"));
const MonitoringPage = lazy(() => import("./pages/MonitoringPage"));
const AddProductPage = lazy(() => import("./pages/AddProductPage"));
const ProductPage = lazy(() => import("./pages/ProductPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

// Links in emails sent before products existed pointed at /items/:id (same id).
function LegacyItemRedirect() {
  return <Navigate to={`/products/${useParams().id}`} replace />;
}

function usePendingCount(): number {
  const [count, setCount] = useState(0);
  const location = useLocation();
  useEffect(() => {
    let alive = true;
    const load = () => listProposals("pending").then((ps) => alive && setCount(ps.length)).catch(() => {});
    load();
    const timer = window.setInterval(load, 20_000);
    window.addEventListener(PROPOSALS_CHANGED, load);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener(PROPOSALS_CHANGED, load);
    };
  }, [location.pathname]);
  return count;
}

const COLLAPSE_KEY = "priceops.sidebar-collapsed";
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function PageFallback() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label="Loading">
      <div className="space-y-3"><Skeleton className="h-3 w-24" /><Skeleton className="h-9 w-64" /><Skeleton className="h-3 w-96 max-w-full" /></div>
      <Skeleton className="h-40 rounded-[14px]" />
      <div className="space-y-2"><Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
    </div>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="eyebrow">Error 404</p>
      <h1 className="display mt-3 text-[44px] leading-none">Off the ledger.</h1>
      <p className="mt-3 text-[13px] text-muted">This page doesn't exist, or the link is from an older version of Price Tracker.</p>
      <div className="mt-6 flex justify-center gap-2">
        <Link to="/" className="btn-primary">Back to overview</Link>
        <Link to="/products" className="btn-ghost">Products</Link>
      </div>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const pending = usePendingCount();
  const [theme, setTheme] = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [reviewer, setReviewer] = useState(loadReviewer);
  const openPalette = useCallback(() => setPaletteOpen(true), []);

  useEffect(() => setNavOpen(false), [location.pathname]);
  useEffect(() => {
    const sync = () => setReviewer(loadReviewer());
    window.addEventListener(REVIEWER_CHANGED, sync);
    return () => window.removeEventListener(REVIEWER_CHANGED, sync);
  }, []);
  // "[" collapses or expands the sidebar (not while typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "[" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      toggleCollapsed();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  function toggleCollapsed() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* storage unavailable */
      }
      return !c;
    });
  }

  const railWidth = collapsed ? "lg:pl-[72px]" : "lg:pl-[248px]";

  return (
    <MotionConfig reducedMotion="user">
      <ConfirmProvider>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-[6px] focus:bg-raised focus:px-3 focus:py-2 focus:shadow-pop">
          Skip to content
        </a>

        {/* Desktop: fixed sidebar (full or icon rail) */}
        <aside className={`fixed inset-y-0 left-0 z-30 hidden border-r border-line bg-rail lg:block ${collapsed ? "w-[72px]" : "w-[248px]"}`}>
          <Sidebar pending={pending} reviewer={reviewer} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        </aside>

        {/* Mobile / tablet: slide-in sidebar */}
        <AnimatePresence>
          {navOpen && (
            <>
              <motion.div
                key="scrim"
                className="fixed inset-0 z-30 bg-gray-900/40 lg:hidden"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { duration: 0.2 } }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
                onClick={() => setNavOpen(false)}
              />
              <motion.aside
                key="nav"
                role="dialog"
                aria-label="Navigation"
                className="fixed inset-y-0 left-0 z-40 w-[272px] border-r border-line bg-rail shadow-pop lg:hidden"
                initial={{ transform: "translateX(-100%)" }}
                animate={{ transform: "translateX(0%)", transition: { duration: 0.28, ease: [0.32, 0.72, 0, 1] } }}
                exit={{ transform: "translateX(-100%)", transition: { duration: 0.2, ease: EASE_OUT } }}
              >
                <Sidebar id="drawer" pending={pending} reviewer={reviewer} onNavigate={() => setNavOpen(false)} />
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        <div className={railWidth}>
          <TopBar pending={pending} onMenu={() => setNavOpen(true)} onSearch={openPalette} />
          <main id="main" className="mx-auto w-full max-w-[1320px] px-4 pb-20 pt-7 sm:px-6 lg:px-10 lg:pt-10">
            <Suspense fallback={<PageFallback />}>
              {/* Enter-only fade keyed by route: the new page never waits for the old one to leave. */}
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, transform: "translateY(4px)" }}
                animate={{ opacity: 1, transform: "translateY(0px)", transition: { duration: 0.2, ease: EASE_OUT } }}
              >
                <Routes location={location}>
                  <Route path="/" element={<OverviewPage />} />
                  <Route path="/products" element={<ProductsPage />} />
                  <Route path="/recommendations" element={<RecommendationsPage />} />
                  <Route path="/approvals" element={<ApprovalsPage />} />
                  <Route path="/monitoring" element={<MonitoringPage />} />
                  <Route path="/add" element={<AddProductPage />} />
                  <Route path="/products/:id" element={<ProductPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/items/:id" element={<LegacyItemRedirect />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </motion.div>
            </Suspense>
          </main>
        </div>

        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} setTheme={setTheme} />
        <Toaster
          position="bottom-right"
          theme={theme}
          closeButton
          toastOptions={{
            classNames: {
              toast: "!rounded-[12px] !border !border-line !bg-raised !text-ink !shadow-pop !font-sans !text-[13px]",
              title: "!font-medium",
              description: "!text-muted",
              actionButton: "!bg-brand !text-on-brand",
              success: "[&_[data-icon]]:!text-good",
              warning: "[&_[data-icon]]:!text-warn",
              error: "[&_[data-icon]]:!text-bad",
            },
          }}
        />
      </ConfirmProvider>
    </MotionConfig>
  );
}
