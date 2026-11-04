// @vitest-environment happy-dom
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScreenBoundary } from "./components/ScreenBoundary";
import { lazyScreen } from "./lazyScreen";

function Hello({ name }: { name: string }) {
  return <p>hello {name}</p>;
}

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("lazyScreen", () => {
  const root = document.createElement("div");
  afterEach(() => render(null, root));

  it("shows a skeleton, then the loaded screen, and loads the chunk once", async () => {
    const load = vi.fn(async () => Hello);
    const Lazy = lazyScreen(load);
    await act(async () => {
      render(<Lazy name="a" />, root);
    });
    expect(root.textContent).not.toContain("hello");
    await flush();
    expect(root.textContent).toBe("hello a");

    render(null, root);
    await act(async () => {
      render(<Lazy name="b" />, root);
    });
    expect(root.textContent).toBe("hello b"); // already loaded: no skeleton
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("reports a failed load to the screen boundary and retries on the next mount", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const load = vi
      .fn<() => Promise<typeof Hello>>()
      .mockRejectedValueOnce(new Error("chunk failed"))
      .mockResolvedValue(Hello);
    const Lazy = lazyScreen(load);
    await act(async () => {
      render(
        <ScreenBoundary resetKey="1">
          <Lazy name="x" />
        </ScreenBoundary>,
        root,
      );
    });
    await flush();
    expect(root.textContent).toContain("Tuhle obrazovku se nepodařilo zobrazit");

    render(null, root);
    await act(async () => {
      render(<Lazy name="y" />, root);
    });
    await flush();
    expect(root.textContent).toBe("hello y");
    expect(load).toHaveBeenCalledTimes(2);
  });
});
