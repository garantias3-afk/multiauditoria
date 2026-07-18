import { CoreProtocolError, parseCoreEvent, type CoreEvent } from "./types";

const MAX_SSE_FRAME_CHARS = 1024 * 1024;

export class SseParser {
  private readonly decoder = new TextDecoder();
  private textBuffer = "";
  private dataLines: string[] = [];
  private frameChars = 0;
  private finished = false;

  push(chunk: Uint8Array): CoreEvent[] {
    if (this.finished) {
      throw new CoreProtocolError("No se pueden agregar bytes después de cerrar el parser SSE");
    }
    this.textBuffer += this.decoder.decode(chunk, { stream: true });
    const events = this.consumeCompleteLines();
    if (this.textBuffer.length > MAX_SSE_FRAME_CHARS) {
      throw new CoreProtocolError("El frame SSE supera el límite de 1 MiB del cliente");
    }
    return events;
  }

  finish(): CoreEvent[] {
    if (this.finished) {
      return [];
    }
    this.finished = true;
    this.textBuffer += this.decoder.decode();

    const events = this.consumeCompleteLines();
    if (this.textBuffer.length > 0) {
      events.push(...this.consumeLine(this.textBuffer.replace(/\r$/, "")));
      this.textBuffer = "";
    }
    events.push(...this.dispatchData());
    return events;
  }

  private consumeCompleteLines(): CoreEvent[] {
    const events: CoreEvent[] = [];
    let newlineIndex = this.textBuffer.indexOf("\n");

    while (newlineIndex !== -1) {
      const rawLine = this.textBuffer.slice(0, newlineIndex);
      this.textBuffer = this.textBuffer.slice(newlineIndex + 1);
      events.push(...this.consumeLine(rawLine.replace(/\r$/, "")));
      newlineIndex = this.textBuffer.indexOf("\n");
    }
    return events;
  }

  private consumeLine(line: string): CoreEvent[] {
    if (line === "") {
      return this.dispatchData();
    }
    this.frameChars += line.length + 1;
    if (this.frameChars > MAX_SSE_FRAME_CHARS) {
      throw new CoreProtocolError("El frame SSE supera el límite de 1 MiB del cliente");
    }
    if (line.startsWith(":")) {
      return [];
    }

    const colonIndex = line.indexOf(":");
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
    let value = colonIndex === -1 ? "" : line.slice(colonIndex + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "data") {
      this.dataLines.push(value);
    }
    return [];
  }

  private dispatchData(): CoreEvent[] {
    if (this.dataLines.length === 0) {
      this.frameChars = 0;
      return [];
    }

    const payload = this.dataLines.join("\n");
    this.dataLines = [];
    this.frameChars = 0;
    let decoded: unknown;
    try {
      decoded = JSON.parse(payload);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new CoreProtocolError(`JSON inválido en frame SSE: ${detail}`);
    }
    return [parseCoreEvent(decoded)];
  }
}
