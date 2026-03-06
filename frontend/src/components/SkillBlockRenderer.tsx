import type { FeedbackAction, FeedbackChoice, LineChartBlock, LineChartPoint, UiBlock } from "../types";
import { MarkdownContent } from "./MarkdownContent";

function buildPolyline(points: LineChartPoint[], width: number, height: number, padding: number): string {
  if (points.length === 0) return "";
  const innerWidth = width - padding * 2;
  const innerHeight = height - padding * 2;
  const values = points.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = maxValue - minValue || Math.max(Math.abs(maxValue), 1) * 0.05;

  const coords = points.map((point, index) => {
    const x = points.length <= 1 ? width / 2 : padding + (innerWidth * index) / (points.length - 1);
    const ratio = (point.value - minValue) / span;
    const y = padding + innerHeight - ratio * innerHeight;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return coords.join(" ");
}

function formatChartValue(value: number): string {
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Math.abs(value) >= 10) return value.toFixed(2);
  return value.toFixed(4);
}

function frequencyLabel(value: string): string {
  if (value === "D") return "日次";
  if (value === "M") return "月次";
  if (value === "Q") return "四半期";
  if (value === "A") return "年次";
  return value;
}

function LineChartCard({ chart }: { chart: LineChartBlock }) {
  const width = 680;
  const height = 260;
  const padding = 28;
  const polyline = buildPolyline(chart.points, width, height, padding);
  const values = chart.points.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const middlePoint = chart.points[Math.floor((chart.points.length - 1) / 2)];

  return (
    <section className="skill-chart-card">
      <div className="chart-label">
        <span>{chart.title}</span>
        <span>{frequencyLabel(chart.frequency)}</span>
      </div>
      <svg className="skill-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${chart.title} 時系列`}>
        <line className="chart-axis" x1={padding} y1={padding} x2={padding} y2={height - padding} />
        <line className="chart-axis" x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} />
        <polyline className="chart-line" points={polyline} />
        <text className="chart-y-label" x={padding + 6} y={padding + 12}>
          max {formatChartValue(maxValue)}
        </text>
        <text className="chart-y-label" x={padding + 6} y={height - padding - 6}>
          min {formatChartValue(minValue)}
        </text>
        <text className="chart-x-label" x={padding} y={height - 8}>
          {chart.points[0].time}
        </text>
        <text className="chart-x-label" x={width / 2} y={height - 8} textAnchor="middle">
          {middlePoint.time}
        </text>
        <text className="chart-x-label" x={width - padding} y={height - 8} textAnchor="end">
          {chart.points[chart.points.length - 1].time}
        </text>
      </svg>
    </section>
  );
}

export function SkillBlockRenderer(props: {
  blocks: UiBlock[];
  onFeedback?: (action: FeedbackAction, choice: FeedbackChoice) => void;
}) {
  const { blocks, onFeedback } = props;

  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === "markdown") {
          return <MarkdownContent key={`markdown-${index}`} content={block.content} />;
        }
        if (block.type === "line_chart") {
          return <LineChartCard key={`chart-${index}`} chart={block} />;
        }
        return (
          <section className="artifact-card-list" key={`cards-${index}`}>
            {block.title && <h4 className="artifact-card-list-title">{block.title}</h4>}
            {block.sections.map((section) => (
              <section className="audit-news-view-section" key={section.id}>
                <header className="audit-news-view-header">
                  <h4>{section.title}</h4>
                  {section.badge && <span className={`priority-chip ${section.badge.tone}`}>{section.badge.label}</span>}
                </header>
                {section.summary && <p className="audit-news-view-summary">{section.summary}</p>}
                {section.items.length > 0 ? (
                  section.items.map((item) => (
                    <section className="audit-news-card" key={item.id}>
                      <header className="audit-news-card-header">
                        <h4>{item.title}</h4>
                        {item.badge && <span className={`priority-chip ${item.badge.tone}`}>{item.badge.label}</span>}
                      </header>
                      {item.metadata.length > 0 && (
                        <p className="audit-news-meta">
                          {item.metadata.map((row) => row.value).join(" • ")}
                        </p>
                      )}
                      {item.lines.map((line) => (
                        <p className="audit-news-line" key={`${item.id}:${line.label}`}>
                          <strong>{line.label}:</strong> {line.value}
                        </p>
                      ))}
                      {item.links.map((link) => (
                        <p className="audit-news-link" key={`${item.id}:${link.url}`}>
                          <a href={link.url} target="_blank" rel="noreferrer">
                            {link.label}
                          </a>
                        </p>
                      ))}
                      {item.actions.length > 0 && (
                        <div className="audit-news-actions">
                          {item.actions.map((action) =>
                            action.choices.map((choice) => (
                              <button
                                key={`${action.run_id}:${action.item_id}:${choice.value}`}
                                type="button"
                                className={`audit-action-btn ${action.selected === choice.value ? "active" : ""}`}
                                disabled={Boolean(action.selected)}
                                onClick={() => onFeedback?.(action, choice)}
                              >
                                {choice.label}
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </section>
                  ))
                ) : (
                  <section className="audit-news-card audit-news-empty-card">
                    <p className="audit-news-line">{section.empty_message || "表示できる項目はありません。"}</p>
                  </section>
                )}
              </section>
            ))}
          </section>
        );
      })}
    </>
  );
}
