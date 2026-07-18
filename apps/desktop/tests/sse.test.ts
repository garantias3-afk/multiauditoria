import { describe, expect, it } from "vitest";

import { SseParser } from "../src/core/sse";
import { CoreProtocolError, type CoreEvent } from "../src/core/types";

const encoder = new TextEncoder();

function frame(event: CoreEvent, newline = "\n"): string {
  return `data: ${JSON.stringify(event)}${newline}${newline}`;
}

function feed(parser: SseParser, chunks: Uint8Array[]): CoreEvent[] {
  return chunks.flatMap((chunk) => parser.push(chunk));
}

describe("SseParser", () => {
  it("parsea varios frames y los ocho tipos contractuales en orden", () => {
    const events: CoreEvent[] = [
      { type: "token", text: "A" },
      { type: "tool_start", tool: "search", args: { q: "x" } },
      { type: "tool_end", tool: "search", result_summary: "1 resultado" },
      {
        type: "brain_switch",
        from: "LOCAL",
        to: "FREE_QUOTA",
        reason: "fallback",
        identity: {
          model_id: "free-1",
          provider_name: "Mock",
          tier: "FREE_QUOTA",
          cost_class: "free",
        },
      },
      {
        type: "research_progress",
        iteration: 1,
        of: 2,
        queries: ["q"],
        sources_read: ["source"],
        cost_usd: 0,
      },
      { type: "confirm_request", tool: "write", args: { path: "a" }, confirm_id: "c-1" },
      { type: "final", text: "AB" },
      { type: "error", message: "otro turno falló" },
    ];
    const parser = new SseParser();

    const parsed = parser.push(encoder.encode(events.map((event) => frame(event)).join("")));

    expect(parsed).toEqual(events);
    expect(parser.finish()).toEqual([]);
  });

  it("preserva UTF-8 cuando un carácter multibyte queda partido entre chunks", () => {
    const parser = new SseParser();
    const event: CoreEvent = { type: "token", text: "á🚀fin" };
    const bytes = encoder.encode(frame(event));
    const rocket = encoder.encode("🚀");
    const rocketStart = bytes.findIndex((byte, index) =>
      rocket.every((rocketByte, offset) => bytes[index + offset] === rocketByte),
    );
    expect(rocketStart).toBeGreaterThan(0);

    const parsed = feed(parser, [
      bytes.slice(0, rocketStart + 1),
      bytes.slice(rocketStart + 1, rocketStart + 3),
      bytes.slice(rocketStart + 3),
    ]);

    expect(parsed).toEqual([event]);
  });

  it("tolera que cada byte sea un chunk, incluidos CRLF y el separador del frame", () => {
    const parser = new SseParser();
    const event: CoreEvent = { type: "token", text: "límite 🚀" };
    const bytes = encoder.encode(frame(event, "\r\n"));
    const byteChunks = Array.from({ length: bytes.length }, (_unused, index) =>
      bytes.slice(index, index + 1),
    );

    expect(feed(parser, byteChunks)).toEqual([event]);
    expect(parser.finish()).toEqual([]);
  });

  it("acepta CRLF, comentarios SSE y campos ajenos a data", () => {
    const parser = new SseParser();
    const bytes = encoder.encode(
      ": keepalive\r\nid: 19\r\nevent: message\r\n" +
        frame({ type: "token", text: "ok" }, "\r\n"),
    );

    expect(parser.push(bytes)).toEqual([{ type: "token", text: "ok" }]);
  });

  it("une múltiples líneas data antes de decodificar JSON", () => {
    const parser = new SseParser();
    const chunk = 'data: {"type":"token",\n' + 'data: "text":"multilínea"}\n\n';

    expect(parser.push(encoder.encode(chunk))).toEqual([
      { type: "token", text: "multilínea" },
    ]);
  });

  it("rechaza JSON inválido y eventos desconocidos", () => {
    const malformed = new SseParser();
    expect(() => malformed.push(encoder.encode("data: {not-json}\n\n"))).toThrow(
      /JSON inválido/,
    );

    const unknown = new SseParser();
    expect(() =>
      unknown.push(encoder.encode('data: {"type":"inventado"}\n\n')),
    ).toThrow(/no reconocido/);
  });

  it("no emite un frame incompleto antes de finish y falla si el JSON quedó truncado", () => {
    const parser = new SseParser();

    expect(parser.push(encoder.encode('data: {"type":"token","text":"cor'))).toEqual([]);
    expect(() => parser.finish()).toThrow(CoreProtocolError);
  });

  it("no permite agregar bytes después de cerrar el parser", () => {
    const parser = new SseParser();
    parser.finish();

    expect(() => parser.push(encoder.encode(frame({ type: "final", text: "tarde" })))).toThrow(
      /después de cerrar/,
    );
  });

  it("acota también muchas líneas data vacías sin separador de frame", () => {
    const parser = new SseParser();
    const manyEmptyDataLines = "data:\n".repeat(180_000);

    expect(() => parser.push(encoder.encode(manyEmptyDataLines))).toThrow(/1 MiB/);
  });

  it("despacha en finish un data completo aunque EOF llegue sin línea en blanco", () => {
    const parser = new SseParser();
    const event: CoreEvent = { type: "final", text: "último frame" };
    const unterminatedFrame = `data: ${JSON.stringify(event)}`;

    expect(parser.push(encoder.encode(unterminatedFrame))).toEqual([]);
    expect(parser.finish()).toEqual([event]);
    expect(parser.finish()).toEqual([]);
  });
});
