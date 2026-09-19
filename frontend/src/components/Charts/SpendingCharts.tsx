import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchSpendingAnalytics, type AnalyticsResult } from "../../api/statement";
import { useTransactionStore } from "../../store/transactionStore";

/**
 * Two charts for the Bank statements tab: a category-breakdown pie chart,
 * and a net-savings-trend line chart with a real linear-regression
 * projection (backend/analytics/trend_projection.py) shown as a dashed
 * continuation of the solid historical line.
 *
 * PayNexus had zero charts anywhere before this — every insight was text or
 * a <DataTable> — this is a real UX gap being closed, not decoration (see
 * the paynexus-v2-pending-items.md discussion this was agreed from).
 *
 * Deliberately calls POST /statement/analytics itself (a plain effect on
 * mount + whenever the transaction list changes) rather than routing
 * through chat/agents — this is a passive "always visible" view of your
 * own already-decrypted data, not a question needing an LLM to answer.
 */
export function SpendingCharts() {
  const transactions = useTransactionStore((s) => s.transactions);
  const [analytics, setAnalytics] = useState<AnalyticsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (transactions.length === 0) {
      setAnalytics(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSpendingAnalytics(transactions)
      .then((result) => {
        if (!cancelled) setAnalytics(result);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load charts right now — try again in a moment.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [transactions]);

  if (transactions.length === 0) {
    return null; // nothing to chart yet — StatementUploader/StatementList already cover the empty state
  }
  if (error) {
    return <p className="text-xs text-red-600">{error}</p>;
  }
  if (loading && !analytics) {
    return <p className="text-xs text-slate-400">Loading charts…</p>;
  }
  if (!analytics) {
    return null;
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <CategoryPieChart data={analytics.category_breakdown} />
      <SavingsTrendChart data={analytics.savings_projection} />
    </div>
  );
}

const PIE_COLORS = [
  "var(--color-brand-500)",
  "var(--color-brand-300)",
  "var(--color-brand-700)",
  "#B2836A", // a warm complement to the brand petrol, for categories beyond the brand scale's range
  "#8FA05E",
  "#C77B5E",
  "var(--color-brand-200)",
  "var(--color-brand-800)",
];

function CategoryPieChart({ data }: { data: AnalyticsResult["category_breakdown"] }) {
  if (data.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Spending by category</h3>
        <p className="text-xs text-slate-400">No expense transactions on file yet.</p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-700">Spending by category</h3>
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie
            data={data}
            dataKey="total_spent"
            nameKey="category"
            cx="50%"
            cy="50%"
            outerRadius={90}
            // recharts' own PieLabelRenderProps type doesn't know about our
            // custom nameKey/dataKey field names, only its generic `name`/
            // `percent` -- typed loosely here rather than fighting recharts'
            // generics for a label callback, same pragmatic tradeoff most
            // recharts consumers make.
            label={(props: { name?: string; percent?: number }) =>
              `${props.name ?? ""} (${((props.percent ?? 0) * 100).toFixed(0)}%)`
            }
          >
            {data.map((entry, i) => (
              <Cell key={entry.category} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value: unknown) => `₹${Number(value ?? 0).toLocaleString("en-IN")}`} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function SavingsTrendChart({ data }: { data: AnalyticsResult["savings_projection"] }) {
  if (!data) {
    return (
      <div className="rounded-lg border border-slate-200 p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Net savings trend</h3>
        <p className="text-xs text-slate-400">
          Needs at least 3 periods of statement history to project a trend.
        </p>
      </div>
    );
  }

  // Two series sharing one x-axis: "actual" holds a value only for real
  // historical periods (null afterward), "projected" holds a value only
  // from the last real period onward (null before) -- the standard recharts
  // technique for a solid line continuing as a dashed one, so the chart is
  // honest about which points are real and which are a projection.
  const lastHistoricalValue = data.historical_values[data.historical_values.length - 1];
  const chartData = [
    ...data.historical_periods.map((period, i) => ({
      period,
      actual: data.historical_values[i],
      projected: null as number | null,
    })),
    ...data.projected_periods.map((period, i) => ({
      period,
      actual: null as number | null,
      projected: i === 0 ? lastHistoricalValue : data.projected_values[i - 1],
    })),
  ];
  // The join point needs both series present so the dashed line visually
  // connects to where the solid one ends, rather than leaving a gap.
  chartData[data.historical_periods.length - 1].projected = lastHistoricalValue;

  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-700">Net savings trend</h3>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`} />
          <Tooltip formatter={(value: unknown) => `₹${Number(value ?? 0).toLocaleString("en-IN")}`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="actual"
            name="Actual"
            stroke="var(--color-brand-600)"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="projected"
            name="Projected"
            stroke="var(--color-brand-400)"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={{ r: 3 }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-2 text-[11px] text-slate-400">
        Projection fit quality (R²): {data.r_squared.toFixed(2)} — closer to 1.0 means the trend line
        matches the real history more closely.
      </p>
    </div>
  );
}
