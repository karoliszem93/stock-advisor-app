import { Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Watchlist from "./pages/Watchlist";
import Validations from "./pages/Validations";
import Settings from "./pages/Settings";
import SuggestionDetail from "./pages/SuggestionDetail";
import TickerView from "./pages/TickerView";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-3 py-2 rounded text-sm ${
    isActive
      ? "bg-panel text-accent border border-border"
      : "text-gray-300 hover:bg-panel/50"
  }`;

export default function App() {
  return (
    <div className="flex h-screen">
      <aside className="w-56 shrink-0 border-r border-border bg-panel/40 p-4 flex flex-col gap-1">
        <h1 className="text-lg font-semibold mb-4">stock-advisor</h1>
        <NavLink to="/" end className={navLinkClass}>Dashboard</NavLink>
        <NavLink to="/watchlist" className={navLinkClass}>Watchlist</NavLink>
        <NavLink to="/validations" className={navLinkClass}>Validations</NavLink>
        <NavLink to="/settings" className={navLinkClass}>Settings</NavLink>
        <div className="mt-auto text-xs text-gray-500">
          v0.1 · localhost
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/validations" element={<Validations />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/suggestion/:id" element={<SuggestionDetail />} />
          <Route path="/ticker/:ticker" element={<TickerView />} />
        </Routes>
      </main>
    </div>
  );
}
