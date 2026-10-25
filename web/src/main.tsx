import { render } from "preact";
import { App } from "./App";

const root = document.getElementById("app");
if (root) {
  render(<App />, root);
}

// Register service worker if supported
if ("serviceWorker" in navigator && import.meta.env.MODE !== "test") {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js")
      .catch((err) => {
        // SW registration failed (e.g. self-signed cert or insecure origin)
        console.warn("Service worker registration failed:", err);
      });
  });
}
