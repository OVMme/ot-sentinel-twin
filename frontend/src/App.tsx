import { Compass } from "lucide-react";
import { Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/ui";
import AboutPage from "./pages/AboutPage";
import DetectionPage from "./pages/DetectionPage";
import IncidentDetailPage from "./pages/IncidentDetailPage";
import IncidentsPage from "./pages/IncidentsPage";
import Overview from "./pages/Overview";
import PlantPage from "./pages/PlantPage";
import ReplayPage from "./pages/ReplayPage";
import ReportsPage from "./pages/ReportsPage";
import ScenarioLab from "./pages/ScenarioLab";
import SettingsPage from "./pages/SettingsPage";
import TelemetryPage from "./pages/TelemetryPage";

function NotFound() {
  return (
    <EmptyState icon={Compass} title="Page not found">
      <Link to="/" className="text-cyan hover:underline">Back to overview</Link>
    </EmptyState>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Overview />} />
      <Route path="/plant" element={<PlantPage />} />
      <Route path="/telemetry" element={<TelemetryPage />} />
      <Route path="/detection" element={<DetectionPage />} />
      <Route path="/incidents" element={<IncidentsPage />} />
      <Route path="/incidents/:id" element={<IncidentDetailPage />} />
      <Route path="/scenarios" element={<ScenarioLab />} />
      <Route path="/replay" element={<ReplayPage />} />
      <Route path="/reports" element={<ReportsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default function App() {
  return (
    <Layout>
      <AppRoutes />
    </Layout>
  );
}
