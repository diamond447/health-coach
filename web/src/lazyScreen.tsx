import { ComponentType, FunctionComponent } from "preact";
import { useEffect, useState } from "preact/hooks";
import { Skeleton } from "./components/Skeleton";

/**
 * A screen whose code is a separate chunk, loaded on first use. Shows a skeleton until
 * then; a failed load (offline, deploy in between) throws into the ScreenBoundary, and the
 * next mount tries again.
 */
export function lazyScreen<P extends object>(
  load: () => Promise<ComponentType<P>>,
): FunctionComponent<P> {
  let loaded: ComponentType<P> | null = null;
  let pending: Promise<ComponentType<P>> | null = null;

  return function LazyScreen(props: P) {
    const [, setLoadedAt] = useState(0);
    const [error, setError] = useState<unknown>(null);

    useEffect(() => {
      if (loaded) return;
      let alive = true;
      pending ??= load();
      pending.then(
        (component) => {
          loaded = component;
          if (alive) setLoadedAt(Date.now());
        },
        (err: unknown) => {
          pending = null;
          if (alive) setError(err);
        },
      );
      return () => {
        alive = false;
      };
    }, []);

    if (error) throw error;
    const Screen = loaded;
    if (!Screen) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={240} />
          <Skeleton height={180} />
        </div>
      );
    }
    return <Screen {...props} />;
  };
}
