// @vitest-environment happy-dom
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fixtures } from "./fixtures";
import { JournalScreen } from "./screens/JournalScreen";
import { JournalResponse } from "./types";

describe("JournalScreen interactive writing", () => {
  const root = document.createElement("div");
  beforeEach(() => {
    document.body.appendChild(root);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    render(null, root);
    root.remove();
    vi.restoreAllMocks();
  });

  const baseJournal: JournalResponse = {
    ...fixtures.journal,
    can_write: true,
    log_date: "2026-10-24",
    yesterday: [
      {
        behavior: "sauna",
        name: "Sauna",
        amount: null,
        note: null,
        active: true,
      },
      {
        behavior: "alcohol",
        name: "Alkohol",
        amount: 2.0,
        note: null,
        active: true,
      },
    ],
  };

  it("renders interactive chips with aria-pressed and stepper when can_write is true", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // Check hint text
    expect(root.textContent).toContain(
      "Klepnutím zapíšeš včerejší večer. Jiné věci (třeba „kafe v 15:00“) napiš koučovi v Claude."
    );

    // Alcohol is active and has unit -> shows stepper buttons
    const alcoholBtn = root.querySelector('button[aria-pressed="true"]') as HTMLButtonElement;
    expect(alcoholBtn).not.toBeNull();

    const decBtn = root.querySelector('button[aria-label="Snížit Alkohol"]') as HTMLButtonElement;
    const incBtn = root.querySelector('button[aria-label="Zvýšit Alkohol"]') as HTMLButtonElement;
    expect(decBtn).not.toBeNull();
    expect(incBtn).not.toBeNull();
    expect(root.textContent).toContain("2 nápoje");
  });

  it("toggling an inactive chip calls PUT and activates it", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });
    const apiSendSpy = vi
      .spyOn(api, "apiSend")
      .mockImplementation(async (_method, _url, body: any) => ({
        data: {
          ...baseJournal,
          yesterday: [
            ...baseJournal.yesterday,
            {
              behavior: body.behavior,
              name: "Jídlo < 2 h před spaním",
              amount: body.amount,
              note: body.note,
              active: true,
            },
          ],
        },
        error: null,
        asOf: null,
        isOffline: false,
        sessionExpired: false,
      }));

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // Find late_meal chip (inactive)
    const lateMealBtn = Array.from(root.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Jídlo < 2 h")
    );
    expect(lateMealBtn).not.toBeNull();
    expect(lateMealBtn?.getAttribute("aria-pressed")).toBe("false");

    await act(async () => {
      lateMealBtn?.click();
    });

    expect(apiSendSpy).toHaveBeenCalledWith("PUT", "/api/journal/entries", {
      date: "2026-10-24",
      behavior: "late_meal",
      amount: null,
      note: null,
    });
    const updatedBtn = Array.from(root.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Jídlo < 2 h")
    );
    expect(updatedBtn?.getAttribute("aria-pressed")).toBe("true");
  });

  it("toggling an active chip calls DELETE and deactivates it", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });
    const apiSendSpy = vi.spyOn(api, "apiSend").mockResolvedValue({
      data: { deleted: true },
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const saunaBtn = Array.from(root.querySelectorAll("button")).find(
      (b) => b.textContent === "Sauna"
    );
    expect(saunaBtn?.getAttribute("aria-pressed")).toBe("true");

    await act(async () => {
      saunaBtn?.click();
    });

    expect(apiSendSpy).toHaveBeenCalledWith(
      "DELETE",
      "/api/journal/entries?date=2026-10-24&behavior=sauna"
    );
    expect(saunaBtn?.getAttribute("aria-pressed")).toBe("false");
  });

  it("stepper updates amount and debounces PUT call", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });
    const apiSendSpy = vi.spyOn(api, "apiSend").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const incBtn = root.querySelector('button[aria-label="Zvýšit Alkohol"]') as HTMLButtonElement;
    expect(root.textContent).toContain("2 nápoje");

    await act(async () => {
      incBtn.click();
    });
    // Immediately updated in UI
    expect(root.textContent).toContain("3 nápoje");
    expect(apiSendSpy).not.toHaveBeenCalled();

    // Fast-forward debounce
    await act(async () => {
      vi.advanceTimersByTime(650);
    });

    expect(apiSendSpy).toHaveBeenCalledWith("PUT", "/api/journal/entries", {
      date: "2026-10-24",
      behavior: "alcohol",
      amount: 3,
      note: null,
    });
  });

  it("rolls back and shows Czech error line on failure", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: baseJournal,
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });
    vi.spyOn(api, "apiSend").mockResolvedValue({
      data: null,
      error: "Nepodařilo se uložit, zkus to znovu",
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const saunaBtn = Array.from(root.querySelectorAll("button")).find(
      (b) => b.textContent === "Sauna"
    );
    await act(async () => {
      saunaBtn?.click();
    });

    // Rollback: sauna should still be active, error line displayed
    expect(root.textContent).toContain("Nepodařilo se uložit, zkus to znovu");
    expect(saunaBtn?.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders read-only view when can_write is false", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue({
      data: { ...baseJournal, can_write: false },
      error: null,
      asOf: null,
      isOffline: false,
      sessionExpired: false,
    });

    await act(async () => {
      render(<JournalScreen date="2026-10-25" />, root);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // No stepper buttons, no button chips
    const incBtn = root.querySelector('button[aria-label="Zvýšit Alkohol"]');
    expect(incBtn).toBeNull();
    const pressedButtons = root.querySelectorAll('button[aria-pressed]');
    expect(pressedButtons.length).toBe(0);
  });
});
