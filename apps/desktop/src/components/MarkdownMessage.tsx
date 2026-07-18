import {
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

export interface MarkdownMessageProps {
  content: string;
  className?: string;
}

type CopyState = "idle" | "copied" | "failed";

type MarkdownPreProps = ComponentPropsWithoutRef<"pre"> & {
  node?: unknown;
};

function textFromNode(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(textFromNode).join("");
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return textFromNode(node.props.children);
  }
  return "";
}

function MarkdownCodeBlock({ children, node: _node, ...props }: MarkdownPreProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const copySequence = useRef(0);
  const code = textFromNode(children).replace(/\n$/, "");

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (resetTimer.current !== null) {
        clearTimeout(resetTimer.current);
      }
    };
  }, []);

  const copy = async () => {
    copySequence.current += 1;
    const sequence = copySequence.current;
    if (resetTimer.current !== null) {
      clearTimeout(resetTimer.current);
      resetTimer.current = null;
    }

    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(code);
      if (!mounted.current || sequence !== copySequence.current) return;
      setCopyState("copied");
    } catch {
      if (!mounted.current || sequence !== copySequence.current) return;
      setCopyState("failed");
    }

    if (!mounted.current || sequence !== copySequence.current) return;
    if (resetTimer.current !== null) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => {
      if (!mounted.current || sequence !== copySequence.current) return;
      setCopyState("idle");
      resetTimer.current = null;
    }, 2_000);
  };

  const label =
    copyState === "copied"
      ? "Copiado"
      : copyState === "failed"
        ? "No se pudo copiar"
        : "Copiar";

  return (
    <div className="code-block">
      <div className="code-block__toolbar">
        <button
          className="code-block__copy"
          type="button"
          onClick={() => void copy()}
          aria-label="Copiar bloque de código"
        >
          {label}
        </button>
        <span className="sr-only" role="status" aria-live="polite">
          {copyState === "copied"
            ? "El código se copió al portapapeles."
            : copyState === "failed"
              ? "No se pudo copiar el código al portapapeles."
              : ""}
        </span>
      </div>
      <pre {...props}>{children}</pre>
    </div>
  );
}

export function MarkdownMessage({ content, className }: MarkdownMessageProps) {
  const classes = ["markdown-message", className].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        skipHtml
        components={{
          pre: MarkdownCodeBlock,
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" />
          ),
          img: ({ node: _node, alt }) => (
            <span className="markdown-message__blocked-image" role="note">
              Imagen externa bloqueada{alt ? `: ${alt}` : ""}
            </span>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownMessage;
