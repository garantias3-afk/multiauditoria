// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarkdownMessage } from "../src/components/MarkdownMessage";

function deferred(): {
  promise: Promise<void>;
  resolve: () => void;
  reject: (error: Error) => void;
} {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("MarkdownMessage clipboard", () => {
  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("sólo aplica el resultado del clic de copia más reciente y limpia al desmontar", async () => {
    const first = deferred();
    const second = deferred();
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(createElement(MarkdownMessage, { content: "```ts\nconst x = 1;\n```" }));
    });
    const button = container.querySelector<HTMLButtonElement>(".code-block__copy")!;

    await act(async () => {
      button.click();
      button.click();
    });
    await act(async () => second.resolve());
    expect(button.textContent).toBe("Copiado");
    await act(async () => first.reject(new Error("resultado viejo")));
    expect(button.textContent).toBe("Copiado");

    await act(async () => root.unmount());
    expect(() => vi.runAllTimers()).not.toThrow();
    container.remove();
  });
});
