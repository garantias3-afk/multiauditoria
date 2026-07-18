import { describe, expect, it } from "vitest";

import {
  CoreProtocolError,
  parseBrainsResponse,
  parseCoreEvent,
  type CoreEvent,
} from "../src/core/types";

const validEvents: CoreEvent[] = [
  { type: "token", text: "Hola" },
  { type: "tool_start", tool: "read_file", args: { path: "/tmp/a.txt" } },
  { type: "tool_end", tool: "read_file", result_summary: { bytes: 12 } },
  {
    type: "brain_switch",
    from: "LOCAL",
    to: "PAID_CHEAP",
    reason: "El modelo local no pudo resolverlo",
    identity: {
      model_id: "mock-paid-1",
      provider_name: "Mock Provider",
      tier: "PAID_CHEAP",
      cost_class: "low",
    },
  },
  {
    type: "research_progress",
    iteration: 2,
    of: 4,
    queries: ["fuente primaria"],
    sources_read: 7,
    cost_usd: 0.00125,
  },
  {
    type: "confirm_request",
    tool: "write_file",
    args: { path: "/tmp/result.txt" },
    confirm_id: "confirm-123",
  },
  { type: "final", text: "Respuesta completa" },
  { type: "error", message: "El Core no pudo continuar" },
];

describe("parseCoreEvent", () => {
  it("acepta y conserva los ocho eventos del contrato CORE-API", () => {
    expect(validEvents.map((event) => parseCoreEvent(event))).toEqual(validEvents);
  });

  it.each([
    ["un valor nulo", null],
    ["un array", []],
    ["un objeto sin type", { text: "hola" }],
    ["un type desconocido", { type: "made_up", text: "hola" }],
    ["un token sin texto", { type: "token" }],
    ["un confirm_id vacío", { type: "confirm_request", tool: "write", args: {}, confirm_id: "" }],
    ["un error sin mensaje visible", { type: "error", message: "" }],
    ["un costo no finito", {
      type: "research_progress",
      iteration: 1,
      of: 1,
      queries: [],
      sources_read: 0,
      cost_usd: Number.POSITIVE_INFINITY,
    }],
  ])("rechaza %s", (_label, value) => {
    expect(() => parseCoreEvent(value)).toThrow(CoreProtocolError);
  });

  it("rechaza un brain_switch cuya identidad no coincide con el tier de destino", () => {
    expect(() =>
      parseCoreEvent({
        type: "brain_switch",
        from: "LOCAL",
        to: "VIBE",
        reason: "Escalamiento",
        identity: {
          model_id: "wrong-tier",
          provider_name: "Mock",
          tier: "PAID_CHEAP",
          cost_class: "expensive",
        },
      }),
    ).toThrow(/identity\.tier/);
  });

  it.each([
    ["args de tool_start", { type: "tool_start", tool: "read_file" }],
    ["result_summary de tool_end", { type: "tool_end", tool: "read_file" }],
    [
      "queries de research_progress",
      {
        type: "research_progress",
        iteration: 1,
        of: 2,
        sources_read: [],
        cost_usd: 0,
      },
    ],
    [
      "sources_read de research_progress",
      {
        type: "research_progress",
        iteration: 1,
        of: 2,
        queries: [],
        cost_usd: 0,
      },
    ],
    [
      "args de confirm_request",
      { type: "confirm_request", tool: "write_file", confirm_id: "confirm-1" },
    ],
  ])("rechaza la ausencia del campo contractual obligatorio %s", (_label, value) => {
    expect(() => parseCoreEvent(value)).toThrow(/campo obligatorio/);
  });

  it.each([
    ["iteration", -1],
    ["of", -2],
    ["cost_usd", -0.0001],
  ])("rechaza research_progress con %s negativo", (field, negativeValue) => {
    expect(() =>
      parseCoreEvent({
        type: "research_progress",
        iteration: 1,
        of: 2,
        queries: [],
        sources_read: [],
        cost_usd: 0,
        [field]: negativeValue,
      }),
    ).toThrow(/no negativo/);
  });

  it("rechaza brains si backend.tier contradice identity.tier", () => {
    expect(() =>
      parseBrainsResponse({
        escalon_activo: "LOCAL",
        backends: [
          {
            tier: "LOCAL",
            alive: true,
            identity: {
              model_id: "contradictory",
              provider_name: "Mock",
              tier: "VIBE",
              cost_class: "expensive",
            },
          },
        ],
        cost_usd_acumulado: 0,
      }),
    ).toThrow(/backend\.tier/);
  });

  it("rechaza un costo acumulado negativo en brains", () => {
    expect(() =>
      parseBrainsResponse({
        escalon_activo: "LOCAL",
        backends: [],
        cost_usd_acumulado: -0.01,
      }),
    ).toThrow(/no negativo/);
  });
});
