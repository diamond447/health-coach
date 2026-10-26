import { useEffect, useState } from "preact/hooks";
import { apiState } from "./api";
import { OfflineBanner } from "./components/OfflineBanner";
import { ScreenBoundary } from "./components/ScreenBoundary";
import { SessionExpiryBanner } from "./components/SessionExpiryBanner";
import { TabBar } from "./components/TabBar";
import { getTodayString } from "./helpers";
import { CalendarScreen } from "./screens/CalendarScreen";
import { HealthspanScreen } from "./screens/HealthspanScreen";
import { JournalScreen } from "./screens/JournalScreen";
import { MainScreen } from "./screens/MainScreen";
import { NutritionScreen } from "./screens/NutritionScreen";
import { RecoveryScreen } from "./screens/RecoveryScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { SleepScreen } from "./screens/SleepScreen";
import { StrainScreen } from "./screens/StrainScreen";
import { TrendsScreen } from "./screens/TrendsScreen";

function parseLocation(): { path: string; date: string } {
  if (typeof window === "undefined") {
    return { path: "/", date: getTodayString() };
  }
  const path = window.location.pathname || "/";
  const params = new URLSearchParams(window.location.search);
  const date = params.get("date") || getTodayString();
  return { path, date };
}

export function App() {
  const [route, setRoute] = useState(parseLocation);
  const [sessionExpired, setSessionExpired] = useState(apiState.sessionExpired);
  const [isOffline, setIsOffline] = useState(apiState.isOffline);
  const [offlineAsOf, setOfflineAsOf] = useState(apiState.offlineAsOf);

  useEffect(() => {
    const unsub = apiState.subscribe(() => {
      setSessionExpired(apiState.sessionExpired);
      setIsOffline(apiState.isOffline);
      setOfflineAsOf(apiState.offlineAsOf);
    });
    return unsub;
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      setRoute(parseLocation());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Intercept anchor clicks for client-side routing
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest("a");
      if (!target) return;

      const href = target.getAttribute("href");
      if (!href) return;

      // Allow external links, anchor links, and modified clicks
      if (
        href.startsWith("http") ||
        href.startsWith("//") ||
        href.startsWith("#") ||
        e.ctrlKey ||
        e.metaKey ||
        e.shiftKey ||
        target.target === "_blank"
      ) {
        return;
      }

      e.preventDefault();
      window.history.pushState({}, "", href);
      setRoute(parseLocation());
      window.scrollTo(0, 0);
    };

    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, []);

  const handleDateChange = (newDate: string) => {
    const params = new URLSearchParams(window.location.search);
    params.set("date", newDate);
    const newUrl = `${route.path}?${params.toString()}`;
    window.history.pushState({}, "", newUrl);
    setRoute({ path: route.path, date: newDate });
  };

  // Screen rendering
  let content = <MainScreen date={route.date} onDateChange={handleDateChange} />;
  const normalizedPath = route.path.replace(/\/+$/, "") || "/";

  switch (normalizedPath) {
    case "/":
      content = <MainScreen date={route.date} onDateChange={handleDateChange} />;
      break;
    case "/recovery":
      content = <RecoveryScreen date={route.date} />;
      break;
    case "/spanek":
      content = <SleepScreen date={route.date} onDateChange={handleDateChange} />;
      break;
    case "/strain":
      content = <StrainScreen date={route.date} onDateChange={handleDateChange} />;
      break;
    case "/jidlo":
      content = <NutritionScreen date={route.date} onDateChange={handleDateChange} />;
      break;
    case "/trendy":
      content = <TrendsScreen date={route.date} />;
      break;
    case "/kalendar":
      content = <CalendarScreen date={route.date} onDateChange={handleDateChange} />;
      break;
    case "/denik":
      content = <JournalScreen date={route.date} />;
      break;
    case "/prehled":
      content = <ReportScreen date={route.date} />;
      break;
    case "/healthspan":
      content = <HealthspanScreen date={route.date} />;
      break;
    default:
      content = <MainScreen date={route.date} onDateChange={handleDateChange} />;
      break;
  }

  return (
    <div
      style={{
        width: "100%",
        maxWidth: "480px",
        minHeight: "100vh",
        margin: "0 auto",
        display: "flex",
        flexDirection: "column",
        background: "#0B0D10",
        color: "#F2F4F7",
        boxSizing: "border-box",
      }}
    >
      {sessionExpired && <SessionExpiryBanner />}
      {isOffline && !sessionExpired && <OfflineBanner asOf={offlineAsOf} />}

      <main
        style={{
          // The bottom padding keeps the last card clear of the fixed tab bar.
          padding:
            "max(16px, env(safe-area-inset-top, 16px)) 16px calc(88px + env(safe-area-inset-bottom, 0px)) 16px",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
          flexGrow: 1,
        }}
      >
        <ScreenBoundary resetKey={`${normalizedPath}?${route.date}`}>{content}</ScreenBoundary>
      </main>

      <TabBar currentPath={normalizedPath} date={route.date} />
    </div>
  );
}
