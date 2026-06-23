import { motion } from "framer-motion";
import type { PipelineStats } from "../types";

export function MetricCards({ stats }: { stats: PipelineStats }) {
  const items = [
    { label: "Documents", value: stats.doc_count },
    { label: "Chunks Indexed", value: stats.chunk_count },
    { label: "Sections", value: stats.section_count },
    { label: "Flags", value: stats.flag_count },
  ];

  return (
    <div className="metrics">
      {items.map((item, i) => (
        <motion.div
          key={item.label}
          className="metric-card"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.08 }}
        >
          <div className="metric-value">{item.value}</div>
          <div className="metric-label">{item.label}</div>
        </motion.div>
      ))}
    </div>
  );
}
