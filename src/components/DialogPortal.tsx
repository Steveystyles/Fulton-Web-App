import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function DialogPortal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const container = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    const overflow = document.body.style.overflow;
    if (root) root.inert = true;
    document.body.style.overflow = "hidden";
    container.current?.querySelector<HTMLElement>("button, a[href], [tabindex='0']")?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(container.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input, textarea, [tabindex='0']") ?? []);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", keyboard, true);
    return () => { if (root) root.inert = wasInert; document.body.style.overflow = overflow; document.removeEventListener("keydown", keyboard, true); previous?.focus(); };
  }, []);
  return createPortal(<div ref={container}>{children}</div>, document.body);
}
