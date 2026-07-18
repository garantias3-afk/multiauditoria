const normalCostFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const tinyCostFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 6,
});

export function formatCost(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "Costo no disponible";
  }
  if (value > 0 && value < 0.000001) {
    return "<$0.000001";
  }
  if (value > 0 && value < 0.01) {
    return tinyCostFormatter.format(value);
  }
  return normalCostFormatter.format(value);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "tamaño desconocido";
  }
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

export function summarize(value: unknown, maxLength = 220): string {
  if (typeof value === "string") {
    return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
  }

  let rendered: string;
  try {
    rendered = JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    rendered = String(value);
  }
  return rendered.length > maxLength ? `${rendered.slice(0, maxLength - 1)}…` : rendered;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
