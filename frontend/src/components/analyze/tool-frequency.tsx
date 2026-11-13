import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

const ROW_HEIGHT = 26;
const CHAR_WIDTH = 7; // ~12px font
const MAX_LABEL_WIDTH = 200;

interface ToolFrequencyProps {
  data: Record<string, number>;
}

export function ToolFrequency({ data }: ToolFrequencyProps) {
  const chartData = Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([tool, count]) => ({ tool, count }));
  // Room for every bar's label: recharts hides category ticks that would
  // overlap, so the chart grows with the number of bars and every tick is drawn.
  const height = Math.max(160, chartData.length * ROW_HEIGHT + 40);
  const labelWidth = Math.min(
    MAX_LABEL_WIDTH,
    Math.max(60, ...chartData.map((d) => d.tool.length * CHAR_WIDTH + 12)),
  );

  if (chartData.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
        <h3 className="text-sm font-medium text-[var(--fg)] mb-4">
          Tool Usage Frequency
        </h3>
        <p className="text-sm text-[var(--fg-muted)] text-center py-8">
          No tool usage found in this project's workflows.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
      <h3 className="text-sm font-medium text-[var(--fg)] mb-4">
        Tool Usage Frequency
      </h3>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis type="number" tick={{ fill: "var(--fg-muted)", fontSize: 12 }} />
          <YAxis
            type="category"
            dataKey="tool"
            tick={{ fill: "var(--fg-muted)", fontSize: 12 }}
            width={labelWidth}
            interval={0}
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
