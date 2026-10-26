import { lazy, Suspense, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import CookieModal from "./components/CookieModal";
import DetailModal from "./components/DetailModal";
import EditEntryModal from "./components/EditEntryModal";
import QrLoginModal from "./components/QrLoginModal";
import SideBar from "./components/SideBar";
import TerminalPanel from "./components/TerminalPanel";
import TopBar from "./components/TopBar";
import ViewPlatform from "./components/ViewPlatform";
import ViewTimeline from "./components/ViewTimeline";
import {
  closeAccountModal,
  closeQrLogin,
  initStore,
  refreshCurrentView,
  useAppStore,
} from "./store";
const ViewGraph = lazy(() => import("./components/ViewGraph"));

export default function App() {
  const { view, accountModal, qrOpen } = useAppStore(
    useShallow((s) => ({
      view: s.view,
      accountModal: s.accountModal,
      qrOpen: s.qrOpen,
    })),
  );
  useEffect(initStore, []);
  return (
    <div className="app-shell">
      <SideBar />
      <div className="app-main">
        <TopBar />
        <main className="app-content">
          {view === "timeline" ? (
            <ViewTimeline />
          ) : view === "graph" ? (
            <Suspense
              fallback={
                <div className="page-loading">
                  <span className="spinner" />
                  正在加载关系图谱…
                </div>
              }
            >
              <ViewGraph />
            </Suspense>
          ) : (
            <ViewPlatform key={view} platformId={view} />
          )}
        </main>
      </div>
      <TerminalPanel />
      <DetailModal />
      <EditEntryModal />
      <QrLoginModal open={qrOpen} onClose={closeQrLogin} />
      <CookieModal
        open={accountModal.open}
        platform={accountModal.platform}
        onClose={closeAccountModal}
        onSaved={() => void refreshCurrentView()}
      />
    </div>
  );
}
