import { useState } from "react";
import { useStore } from "zustand";
import { useAppStore } from "../store";
import { GraphController } from "./graph/controller";
import { GraphCanvas } from "./graph/GraphCanvas";
import { GraphFooter } from "./graph/GraphFooter";
import { GraphStatus } from "./graph/GraphStatus";
import { GraphToolbar } from "./graph/GraphToolbar";
import { createGraphScope } from "./graph/scope";
import styles from "./ViewGraph.module.css";
export default function ViewGraph() {
  const [controller] = useState(() => new GraphController());
  const snapshot = useStore(controller.store);
  const activeGraphId = useAppStore((s) => s.activeGraphId);
  const scope = createGraphScope(controller, snapshot, activeGraphId);
  return (
    <div className={styles["view-graph"]}>
      <GraphToolbar scope={scope} />
      <GraphStatus scope={scope} />
      <GraphCanvas scope={scope} controller={controller} />
      <GraphFooter scope={scope} />
    </div>
  );
}
