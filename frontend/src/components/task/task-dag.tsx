"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import { TaskNode, type TaskNodeData } from "./task-node";
import type { TaskPlan, TaskStatus } from "@/types/api";

interface TaskDagProps {
  plan: TaskPlan;
  taskStatuses?: Record<string, TaskStatus>;
  readonly?: boolean;
  className?: string;
}

const NODE_WIDTH = 200;
const NODE_HEIGHT = 80;

const nodeTypes: NodeTypes = {
  task: TaskNode,
};

function layoutDag(plan: TaskPlan, statuses: Record<string, TaskStatus>) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 });

  const nodes: Node<TaskNodeData>[] = [];
  const edges: Edge[] = [];

  for (const task of plan.tasks ?? []) {
    g.setNode(task.task_id, { width: NODE_WIDTH, height: NODE_HEIGHT });

    nodes.push({
      id: task.task_id,
      type: "task",
      position: { x: 0, y: 0 },
      data: {
        label: task.title,
        persona: task.assigned_persona,
        status: statuses[task.task_id] ?? task.status,
        description: task.description,
      },
    });

    for (const dep of task.dependencies ?? []) {
      g.setEdge(dep, task.task_id);
      const depStatus = statuses[dep] ?? "pending";
      edges.push({
        id: `${dep}->${task.task_id}`,
        source: dep,
        target: task.task_id,
        animated: depStatus === "running",
        style: {
          stroke: depStatus === "completed" ? "#22c55e" : "#9ca3af",
        },
      });
    }
  }

  dagre.layout(g);

  // Apply computed positions
  for (const node of nodes) {
    const pos = g.node(node.id);
    node.position = {
      x: pos.x - NODE_WIDTH / 2,
      y: pos.y - NODE_HEIGHT / 2,
    };
  }

  return { nodes, edges };
}

export function TaskDag({ plan, taskStatuses = {}, readonly = false, className }: TaskDagProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutDag(plan, taskStatuses),
    [plan, taskStatuses],
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className={className ?? "h-full w-full"}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={readonly ? undefined : onNodesChange}
        onEdgesChange={readonly ? undefined : onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        panOnDrag={!readonly}
        zoomOnScroll={!readonly}
        nodesDraggable={!readonly}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        {!readonly && <Background />}
        {!readonly && <Controls />}
      </ReactFlow>
    </div>
  );
}
