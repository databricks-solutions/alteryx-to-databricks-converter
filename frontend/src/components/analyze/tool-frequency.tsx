import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

interface ToolFrequencyProps {
  data: Record<string, number>;
}

export function ToolFrequency({ data }: ToolFrequencyProps) {
  const chartData = Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([tool, count]) => ({ tool, count }));

  if (chartData.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
        <h3 className="text-sm font-medium text-[var(--fg)] mb-4">
          Tool Usage Frequency
        </h3>
        <p className="text-sm text-[var(--fg-muted)] text-center py-8">
          No tool usage data available. Upload workflows to see frequency analysis.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
      <h3 className="text-sm font-medium text-[var(--fg)] mb-4">
        Tool Usage Frequency
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis type="number" tick={{ fill: "var(--fg-muted)", fontSize: 12 }} />
          <YAxis
            type="category"
            dataKey="tool"
            tick={{ fill: "var(--fg-muted)", fontSize: 12 }}
            width={80}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--bg-card)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
            }}
          />
          <Bar dataKey="count" fill="var(--ring)" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
