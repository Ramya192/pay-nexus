export interface TableData {
  title: string;
  headers: string[];
  rows: string[][];
}

// Matches a currency/count/percentage cell as the backend's *_table()
// builders actually format them — "₹50,000", "↑ ₹5,000", "2" (duplicate
// count), "0.83" (regulatory retrieval distance), "₹50,000 (2026-01)"
// (trends' "value (month)" cells) — but not a plain label that merely
// starts with a digit, like "80C" or a month string on its own. A column
// right-aligns only if every non-empty cell in it matches; a single
// non-matching cell (e.g. a text label) keeps the whole column left-
// aligned rather than guessing.
const NUMERIC_CELL_PATTERN = /^([↑↓→]\s*)?-?₹?\d[\d,]*(\.\d+)?%?( \([^)]*\))?$/;

function isNumericColumn(rows: string[][], colIndex: number): boolean {
  let sawValue = false;
  for (const row of rows) {
    const cell = (row[colIndex] ?? "").trim();
    if (cell === "") continue;
    sawValue = true;
    if (!NUMERIC_CELL_PATTERN.test(cell)) return false;
  }
  return sawValue;
}

/**
 * Renders a table exactly as computed backend-side (tax_calculations.py /
 * payslip_trends.py's *_table() builders) — the agent only ever picks
 * WHICH of these to show, never touches the numbers inside them (see
 * backend/agents/tables.py). Kept deliberately plain: this is where the
 * actual figures live, so legibility matters more than styling here.
 *
 * Numeric columns (currency, counts, percentages) right-align — the one
 * change that makes a column of figures scannable top-to-bottom, per the
 * UI design audit (README) — detected per-column from the actual cell
 * content, not from column position or header text, since every table
 * shape here is backend-defined and none of them tag which columns are
 * numeric.
 */
export function DataTable({ table }: { table: TableData }) {
  const numericCols = table.headers.map((_, i) => isNumericColumn(table.rows, i));

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-left text-xs">
        <caption className="border-b border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs font-semibold text-slate-700 caption-top">
          {table.title}
        </caption>
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/60 text-slate-500">
            {table.headers.map((h, i) => (
              <th
                key={h || i}
                scope="col"
                className={`px-3 py-1.5 font-medium ${numericCols[i] ? "text-right" : "text-left"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0 [&>td]:tabular-nums">
              {row.map((cell, j) => (
                <td
                  key={j}
                  className={`px-3 py-1.5 text-slate-700 ${numericCols[j] ? "text-right" : "text-left"}`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
