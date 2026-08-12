"use client";

import { useMemo } from "react";

export type AnswerBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "list"; items: string[] }
  | { type: "kv"; rows: Array<{ key: string; value: string }> }
  | { type: "table"; headers: string[]; rows: string[][] }
  | {
      type: "chart";
      chartType: "bar" | "line";
      title?: string;
      xLabel?: string;
      yLabel?: string;
      labels: string[];
      series: Array<{ name: string; values: number[] }>;
    };

function splitValuePairs(
  text: string,
): Array<{ key: string; value: string }> | null {
  const pairs = [
    ...text.matchAll(/\b([A-Za-z][A-Za-z0-9]{0,6})\s+([^,;]+?)(?=,|;|$)/g),
  ]
    .map((match) => ({
      key: match[1].trim(),
      value: match[2].trim(),
    }))
    .filter((row) => row.key && row.value && /[0-9.<]/.test(row.value));
  return pairs.length >= 3 ? pairs : null;
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return false;
  // Full row or orphan separator fragment from a broken LLM table
  if (/^\|/.test(trimmed) || /\|$/.test(trimmed)) return true;
  return /^[-:\s|]+$/.test(trimmed);
}

function isSeparatorRow(cells: string[]): boolean {
  return (
    cells.length > 0 &&
    cells.every((cell) => /^:?-{1,}:?$/.test(cell.replace(/\s+/g, "")))
  );
}

function splitTableCells(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

function parseMarkdownTable(lines: string[]): {
  headers: string[];
  rows: string[][];
} | null {
  const meaningful = lines
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    // Drop orphan separator fragments like "---|" left on their own line
    .filter((line) => !/^[-:\s|]+$/.test(line) || line.includes("|"));

  const parsed = meaningful
    .map(splitTableCells)
    .filter((cells) => cells.some((cell) => cell.length > 0));

  if (parsed.length < 2) return null;

  const headers = parsed[0];
  let bodyStart = 1;
  if (isSeparatorRow(parsed[1])) {
    bodyStart = 2;
  }

  const colCount = headers.length;
  if (colCount < 2) return null;

  const rows = parsed.slice(bodyStart).map((cells) => {
    const normalized = cells.slice(0, colCount);
    while (normalized.length < colCount) normalized.push("");
    return normalized;
  });

  return { headers, rows };
}

function parseChartPayload(raw: string): Extract<AnswerBlock, { type: "chart" }> | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const labels = Array.isArray(parsed.labels)
      ? parsed.labels.map(String)
      : Array.isArray(parsed.x)
        ? parsed.x.map(String)
        : null;
    if (!labels?.length) return null;

    let series: Array<{ name: string; values: number[] }> = [];
    if (Array.isArray(parsed.series)) {
      series = parsed.series
        .map((item, index) => {
          if (!item || typeof item !== "object") return null;
          const row = item as Record<string, unknown>;
          const values = Array.isArray(row.values)
            ? row.values.map((value) => Number(value))
            : Array.isArray(row.data)
              ? row.data.map((value) => Number(value))
              : null;
          if (!values || values.some((value) => Number.isNaN(value))) return null;
          return {
            name: typeof row.name === "string" && row.name.trim()
              ? row.name.trim()
              : `Series ${index + 1}`,
            values,
          };
        })
        .filter((item): item is { name: string; values: number[] } => Boolean(item));
    } else if (Array.isArray(parsed.values)) {
      const values = parsed.values.map((value) => Number(value));
      if (!values.some((value) => Number.isNaN(value))) {
        series = [
          {
            name:
              typeof parsed.name === "string" && parsed.name.trim()
                ? parsed.name.trim()
                : typeof parsed.yLabel === "string"
                  ? parsed.yLabel
                  : "Value",
            values,
          },
        ];
      }
    }

    if (!series.length) return null;
    const chartType = parsed.type === "line" ? "line" : "bar";
    return {
      type: "chart",
      chartType,
      title: typeof parsed.title === "string" ? parsed.title : undefined,
      xLabel: typeof parsed.xLabel === "string" ? parsed.xLabel : undefined,
      yLabel: typeof parsed.yLabel === "string" ? parsed.yLabel : undefined,
      labels,
      series,
    };
  } catch {
    return null;
  }
}

function flushParagraph(
  lines: string[],
  blocks: AnswerBlock[],
): void {
  const paragraph = lines.join("\n").trim();
  if (!paragraph) return;

  const paraLines = paragraph
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const bulletLines = paraLines.filter((line) =>
    /^([-*•]|\d+\.)\s+/.test(line),
  );
  if (bulletLines.length >= 2 && bulletLines.length === paraLines.length) {
    blocks.push({
      type: "list",
      items: paraLines.map((line) => line.replace(/^([-*•]|\d+\.)\s+/, "")),
    });
    return;
  }

  const sectionChunks = paragraph
    .split(/(?=\bFor\s+[A-Z0-9][^:]{0,80}:)/g)
    .map((part) => part.trim())
    .filter(Boolean);

  if (sectionChunks.length > 1) {
    for (const chunk of sectionChunks) {
      const headingMatch = /^(For\s+.+?)(?:\s*:\s*|\.\s+)/.exec(chunk);
      if (headingMatch) {
        blocks.push({
          type: "heading",
          text: headingMatch[1].replace(/\.$/, ""),
        });
        const rest = chunk.slice(headingMatch[0].length).trim();
        const valuesMatch =
          /(?:measured\s+)?values?\s+are\s*:\s*(.+)$/i.exec(rest);
        if (valuesMatch) {
          const pairs = splitValuePairs(valuesMatch[1]);
          if (pairs) {
            blocks.push({ type: "kv", rows: pairs });
            continue;
          }
        }
        if (rest) blocks.push({ type: "paragraph", text: rest });
        continue;
      }
      blocks.push({ type: "paragraph", text: chunk });
    }
    return;
  }

  const valuesMatch =
    /(?:measured\s+)?values?\s+are\s*:\s*(.+)$/i.exec(paragraph);
  if (valuesMatch) {
    const intro = paragraph.slice(0, valuesMatch.index).trim();
    if (intro) {
      blocks.push({ type: "paragraph", text: intro.replace(/:\s*$/, "") });
    }
    const pairs = splitValuePairs(valuesMatch[1]);
    if (pairs) {
      blocks.push({ type: "kv", rows: pairs });
      return;
    }
  }

  const kvLines = paraLines.filter((line) =>
    /^[-*•]?\s*[A-Za-z][^:]{1,40}:\s+\S/.test(line),
  );
  if (kvLines.length >= 2 && kvLines.length === paraLines.length) {
    blocks.push({
      type: "kv",
      rows: paraLines.map((line) => {
        const cleaned = line.replace(/^[-*•]\s*/, "");
        const idx = cleaned.indexOf(":");
        return {
          key: cleaned.slice(0, idx).trim(),
          value: cleaned.slice(idx + 1).trim(),
        };
      }),
    });
    return;
  }

  blocks.push({ type: "paragraph", text: paragraph });
}

export function toBlocks(answer: string): AnswerBlock[] {
  const normalized = answer.replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];

  const lines = normalized.split("\n");
  const blocks: AnswerBlock[] = [];
  let buffer: string[] = [];
  let index = 0;

  const flushBuffer = () => {
    flushParagraph(buffer, blocks);
    buffer = [];
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    const fenceMatch = /^```(chart|chartjson)\s*$/i.exec(trimmed);
    if (fenceMatch) {
      flushBuffer();
      const payloadLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        payloadLines.push(lines[index]);
        index += 1;
      }
      // consume closing fence if present
      if (index < lines.length && /^```\s*$/.test(lines[index].trim())) {
        index += 1;
      }
      const chart = parseChartPayload(payloadLines.join("\n"));
      if (chart) {
        blocks.push(chart);
      } else if (payloadLines.join("\n").trim()) {
        blocks.push({
          type: "paragraph",
          text: payloadLines.join("\n").trim(),
        });
      }
      continue;
    }

    if (isTableRow(trimmed)) {
      flushBuffer();
      const tableLines: string[] = [];
      while (index < lines.length && isTableRow(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      const table = parseMarkdownTable(tableLines);
      if (table) {
        blocks.push({ type: "table", ...table });
      } else {
        flushParagraph(tableLines, blocks);
      }
      continue;
    }

    if (!trimmed) {
      flushBuffer();
      index += 1;
      continue;
    }

    buffer.push(line);
    index += 1;
  }

  flushBuffer();
  return blocks;
}

function highlightCitations(text: string) {
  const parts = text.split(/(\[C\d+\])/g);
  return parts.map((part, index) => {
    const match = /^\[(C\d+)\]$/.exec(part);
    if (!match) return <span key={index}>{part}</span>;
    const id = match[1];
    return (
      <a
        key={index}
        href={`#cite-${id}`}
        className="mx-0.5 inline-flex items-center rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-accent hover:bg-accent/15"
      >
        {id}
      </a>
    );
  });
}

const SERIES_COLORS = ["#2f6fed", "#0f766e", "#b45309", "#7c3aed", "#be123c"];

function AnswerChart({
  block,
}: {
  block: Extract<AnswerBlock, { type: "chart" }>;
}) {
  const width = 640;
  const height = 280;
  const pad = { top: 28, right: 16, bottom: 56, left: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const allValues = block.series.flatMap((series) => series.values);
  const maxValue = Math.max(...allValues, 0);
  const minValue = Math.min(...allValues, 0);
  const yMax = maxValue === minValue ? maxValue + 1 : maxValue;
  const yMin = minValue < 0 ? minValue : 0;
  const ySpan = yMax - yMin || 1;
  const n = block.labels.length;
  const groupWidth = plotW / Math.max(n, 1);
  const barGap = 0.2;
  const seriesCount = block.series.length;
  const barWidth =
    seriesCount > 0
      ? (groupWidth * (1 - barGap)) / seriesCount
      : groupWidth * 0.6;

  const yScale = (value: number) =>
    pad.top + plotH - ((value - yMin) / ySpan) * plotH;
  const ticks = 4;
  const tickValues = Array.from({ length: ticks + 1 }, (_, i) =>
    yMin + (ySpan * i) / ticks,
  );

  return (
    <div className="overflow-hidden rounded-md border border-border bg-background/60">
      {block.title ? (
        <p className="border-b border-border px-3 py-2 text-sm font-semibold">
          {block.title}
        </p>
      ) : null}
      <div className="overflow-x-auto px-2 py-3">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="mx-auto h-auto w-full max-w-3xl"
          role="img"
          aria-label={block.title || "Chart"}
        >
          {tickValues.map((tick, index) => {
            const y = yScale(tick);
            return (
              <g key={index}>
                <line
                  x1={pad.left}
                  x2={width - pad.right}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeOpacity={0.12}
                />
                <text
                  x={pad.left - 8}
                  y={y + 4}
                  textAnchor="end"
                  className="fill-current text-[10px]"
                  opacity={0.55}
                >
                  {Number.isInteger(tick) ? tick : tick.toFixed(1)}
                </text>
              </g>
            );
          })}

          {block.chartType === "bar"
            ? block.series.map((series, seriesIndex) =>
                series.values.slice(0, n).map((value, labelIndex) => {
                  const x =
                    pad.left +
                    labelIndex * groupWidth +
                    (groupWidth * barGap) / 2 +
                    seriesIndex * barWidth;
                  const y = yScale(Math.max(value, 0));
                  const zeroY = yScale(0);
                  const h = Math.abs(zeroY - yScale(value));
                  return (
                    <rect
                      key={`${seriesIndex}-${labelIndex}`}
                      x={x}
                      y={value >= 0 ? y : zeroY}
                      width={Math.max(barWidth - 2, 2)}
                      height={Math.max(h, 1)}
                      fill={SERIES_COLORS[seriesIndex % SERIES_COLORS.length]}
                      opacity={0.9}
                      rx={2}
                    >
                      <title>
                        {block.labels[labelIndex]} · {series.name}: {value}
                      </title>
                    </rect>
                  );
                }),
              )
            : block.series.map((series, seriesIndex) => {
                const points = series.values
                  .slice(0, n)
                  .map((value, labelIndex) => {
                    const x = pad.left + labelIndex * groupWidth + groupWidth / 2;
                    const y = yScale(value);
                    return `${x},${y}`;
                  })
                  .join(" ");
                const color = SERIES_COLORS[seriesIndex % SERIES_COLORS.length];
                return (
                  <g key={seriesIndex}>
                    <polyline
                      fill="none"
                      stroke={color}
                      strokeWidth={2.5}
                      points={points}
                    />
                    {series.values.slice(0, n).map((value, labelIndex) => {
                      const x =
                        pad.left + labelIndex * groupWidth + groupWidth / 2;
                      const y = yScale(value);
                      return (
                        <circle
                          key={labelIndex}
                          cx={x}
                          cy={y}
                          r={3.5}
                          fill={color}
                        >
                          <title>
                            {block.labels[labelIndex]} · {series.name}: {value}
                          </title>
                        </circle>
                      );
                    })}
                  </g>
                );
              })}

          {block.labels.map((label, labelIndex) => {
            const x = pad.left + labelIndex * groupWidth + groupWidth / 2;
            const short =
              label.length > 14 ? `${label.slice(0, 12).trimEnd()}…` : label;
            return (
              <text
                key={labelIndex}
                x={x}
                y={height - 18}
                textAnchor="middle"
                className="fill-current text-[9px]"
                opacity={0.7}
              >
                {short}
              </text>
            );
          })}

          {block.yLabel ? (
            <text
              x={14}
              y={pad.top + plotH / 2}
              textAnchor="middle"
              transform={`rotate(-90 14 ${pad.top + plotH / 2})`}
              className="fill-current text-[10px]"
              opacity={0.6}
            >
              {block.yLabel}
            </text>
          ) : null}
          {block.xLabel ? (
            <text
              x={pad.left + plotW / 2}
              y={height - 4}
              textAnchor="middle"
              className="fill-current text-[10px]"
              opacity={0.6}
            >
              {block.xLabel}
            </text>
          ) : null}
        </svg>
      </div>
      {block.series.length > 1 ? (
        <ul className="flex flex-wrap gap-3 border-t border-border px-3 py-2 text-xs text-muted">
          {block.series.map((series, index) => (
            <li key={series.name} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{
                  backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length],
                }}
              />
              {series.name}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Build a chart from a numeric markdown table when the user asked to render one. */
function tableToChart(
  headers: string[],
  rows: string[][],
): Extract<AnswerBlock, { type: "chart" }> | null {
  if (rows.length < 2 || headers.length < 2) return null;

  const numericCols = headers
    .map((header, colIndex) => {
      const values = rows.map((row) => {
        const raw = (row[colIndex] || "").replace(/,/g, "").trim();
        const match = /^-?\d+(?:\.\d+)?/.exec(raw);
        return match ? Number(match[0]) : NaN;
      });
      const ok = values.filter((value) => !Number.isNaN(value));
      if (ok.length < Math.ceil(rows.length * 0.7)) return null;
      return { header, colIndex, values };
    })
    .filter(
      (
        item,
      ): item is { header: string; colIndex: number; values: number[] } =>
        Boolean(item),
    );

  if (!numericCols.length) return null;

  // Prefer a distinctive label column (product code) over low-cardinality ones
  let labelCol = 0;
  let bestScore = -1;
  for (let col = 0; col < headers.length; col += 1) {
    if (numericCols.some((item) => item.colIndex === col)) continue;
    const values = rows.map((row) => (row[col] || "").trim()).filter(Boolean);
    if (!values.length) continue;
    const avgLen =
      values.reduce((sum, value) => sum + value.length, 0) / values.length;
    if (avgLen <= 0 || avgLen > 36) continue;
    const unique = new Set(values.map((value) => value.toLowerCase())).size;
    const uniqueness = unique / values.length;
    const score = uniqueness * 10 + Math.min(avgLen, 18) / 18;
    if (score > bestScore) {
      bestScore = score;
      labelCol = col;
    }
  }

  const labels = rows.map((row, index) => {
    const label = (row[labelCol] || "").trim();
    return label || `Row ${index + 1}`;
  });

  return {
    type: "chart",
    chartType: "bar",
    title: undefined,
    xLabel: headers[labelCol],
    yLabel: numericCols.length === 1 ? numericCols[0].header : undefined,
    labels,
    series: numericCols.map((col) => ({
      name: col.header,
      values: col.values.map((value) => (Number.isNaN(value) ? 0 : value)),
    })),
  };
}

/** True only when the user explicitly asks to render/show a chart visual. */
export function wantsRenderedChart(question: string): boolean {
  const q = question.toLowerCase();
  return (
    /\brender(?:ing)?(?:\s+\w+){0,4}\s+chart\b/.test(q) ||
    /\bshow(?:\s+me)?(?:\s+\w+){0,3}\s+(?:as\s+)?(?:a\s+)?chart\b/.test(q) ||
    /\bdisplay(?:\s+\w+){0,3}\s+(?:as\s+)?(?:a\s+)?chart\b/.test(q) ||
    /\bas\s+a\s+chart\b/.test(q) ||
    /\bdraw(?:\s+\w+){0,3}\s+chart\b/.test(q) ||
    /\bchart\s+format\b/.test(q) ||
    /\brender(?:ing)?(?:\s+\w+){0,4}\s+(?:graph|plot)\b/.test(q)
  );
}

export function FormattedAnswer({
  answer,
  allowCharts = false,
}: {
  answer: string;
  allowCharts?: boolean;
}) {
  const blocks = useMemo(() => toBlocks(answer), [answer]);

  if (!blocks.length) {
    return <p className="text-sm text-muted">No answer returned.</p>;
  }

  return (
    <div className="space-y-3 text-[15px] leading-7 text-foreground">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          return (
            <h4
              key={index}
              className="text-sm font-semibold tracking-tight text-foreground"
            >
              {highlightCitations(block.text)}
            </h4>
          );
        }
        if (block.type === "list") {
          return (
            <ul key={index} className="list-disc space-y-1.5 pl-5">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{highlightCitations(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "kv") {
          return (
            <div
              key={index}
              className="overflow-hidden rounded-md border border-border"
            >
              <table className="w-full text-left text-sm">
                <thead className="bg-background text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">Element</th>
                    <th className="px-3 py-2 font-medium">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr
                      key={`${row.key}-${rowIndex}`}
                      className="border-t border-border/80"
                    >
                      <td className="px-3 py-2 font-mono text-[13px] font-semibold">
                        {row.key}
                      </td>
                      <td className="px-3 py-2 font-mono text-[13px]">
                        {highlightCitations(row.value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "table") {
          const autoChart = allowCharts
            ? tableToChart(block.headers, block.rows)
            : null;
          const nextIsChart =
            allowCharts &&
            (blocks[index + 1]?.type === "chart" ||
              blocks[index - 1]?.type === "chart");
          return (
            <div key={index} className="space-y-3">
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full min-w-[28rem] text-left text-sm">
                  <thead className="bg-background text-xs uppercase tracking-wide text-muted">
                    <tr>
                      {block.headers.map((header, headerIndex) => (
                        <th
                          key={headerIndex}
                          className="px-3 py-2 font-medium whitespace-nowrap"
                        >
                          {highlightCitations(header)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr
                        key={rowIndex}
                        className="border-t border-border/80 align-top"
                      >
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            className="px-3 py-2 text-[13px] leading-5"
                          >
                            {highlightCitations(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {autoChart && !nextIsChart ? (
                <AnswerChart block={autoChart} />
              ) : null}
            </div>
          );
        }
        if (block.type === "chart") {
          if (!allowCharts) return null;
          return <AnswerChart key={index} block={block} />;
        }
        return (
          <p key={index} className="whitespace-pre-wrap">
            {highlightCitations(block.text)}
          </p>
        );
      })}
    </div>
  );
}
