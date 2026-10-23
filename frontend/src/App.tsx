import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { api, ApiError, type Session } from "./api";
import { t, useLanguage } from "./i18n";
import { Shell } from "./components/Shell";
import { FirstAccess, Login } from "./pages/Auth";
import { Health } from "./pages/Health";
import { LiveDetail } from "./pages/LiveDetail";
import { Lives } from "./pages/Lives";
import { PublicLive } from "./pages/PublicLive";
import { SettingsPage } from "./pages/SettingsPage";

/** Expired session or pending password change: back to the right entry screen. */
function onAuthError(error: unknown) {
  if (error instanceof ApiError && (error.status === 401 || error.message === "password_change_required")) {
    void queryClient.invalidateQueries({ queryKey: ["session"] });
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
});

function Private() {
  const session = useQuery({ queryKey: ["session"], queryFn: () => api.get<Session>("/api/session") });
  if (!session.data) return session.isError ? <main className="auth-page"><p>{t("Servidor indisponível.")}</p></main> : null;
  if (!session.data.authenticated) return <Login />;
  if (session.data.must_change_password) return <FirstAccess />;
  return (
    <Shell version={session.data.version}>
      <Routes>
        <Route path="/" element={<Lives />} />
        <Route path="/lives/:id" element={<LiveDetail />} />
        <Route path="/saude" element={<Health />} />
        <Route path="/configuracoes" element={<SettingsPage />} />
        <Route path="*" element={<Lives />} />
      </Routes>
    </Shell>
  );
}

export function App() {
  // Switching the language re-renders the tree; the query cache is kept.
  const language = useLanguage();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter key={language}>
        <Routes>
          <Route path="/p/:token" element={<PublicLive />} />
          <Route path="*" element={<Private />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
