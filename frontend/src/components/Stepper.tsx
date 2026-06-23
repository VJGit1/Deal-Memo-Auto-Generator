import { motion } from "framer-motion";
import { STEP_ICONS, STEP_LABELS } from "../types";

interface StepperProps {
  currentStep: number;
  completed?: boolean;
}

export function Stepper({ currentStep, completed = false }: StepperProps) {
  return (
    <div className="stepper">
      {STEP_LABELS.map((label, i) => {
        const stepNum = i + 1;
        let state: "pending" | "active" | "done" = "pending";
        if (completed || stepNum < currentStep) state = "done";
        else if (stepNum === currentStep) state = "active";

        return (
          <div key={label} className={`step ${state}`}>
            <motion.div
              className="step-circle"
              animate={state === "active" ? { scale: [1, 1.08, 1] } : {}}
              transition={{ repeat: Infinity, duration: 1.5 }}
            >
              {state === "done" ? "✓" : STEP_ICONS[i]}
            </motion.div>
            <span className="step-label">{label}</span>
          </div>
        );
      })}
    </div>
  );
}
