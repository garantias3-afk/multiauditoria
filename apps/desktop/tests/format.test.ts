import { describe, expect, it } from "vitest";

import { formatCost } from "../src/utils/format";

describe("formatCost", () => {
  it("formatea cero y costos normales en USD", () => {
    expect(formatCost(0)).toBe("$0.00");
    expect(formatCost(12.5)).toBe("$12.50");
    expect(formatCost(1_234.5)).toBe("$1,234.50");
  });

  it("conserva precisión útil para costos menores a un centavo", () => {
    expect(formatCost(0.001234)).toBe("$0.001234");
    expect(formatCost(0.000001)).toBe("$0.000001");
    expect(formatCost(0.001234)).not.toBe("$0.00");
  });

  it("redondea de manera estable dentro de los límites declarados", () => {
    expect(formatCost(1.23456)).toBe("$1.2346");
    expect(formatCost(0.0000004)).toBe("<$0.000001");
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "no presenta %s como un costo válido",
    (value) => {
      expect(formatCost(value)).toBe("Costo no disponible");
    },
  );
});
