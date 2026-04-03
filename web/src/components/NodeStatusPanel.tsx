"use client";

import { Server, Cpu, MemoryStick, Globe } from "lucide-react";

interface NodeInfo {
  name: string;
  status: "online" | "offline" | "busy";
  cpu: number;
  memory: number;
  model: string;
  browser_layer: boolean;
}

interface Props {
  nodes: NodeInfo[];
}

const statusColor = {
  online: "bg-[var(--accent-green)]",
  busy: "bg-[var(--accent-amber)]",
  offline: "bg-[var(--accent-red)]",
};

const statusLabel = {
  online: "稼働中",
  busy: "ビジー",
  offline: "オフライン",
};

export default function NodeStatusPanel({ nodes }: Props) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">ノードステータス</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {nodes.map((node) => (
          <div
            key={node.name}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
          >
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-[var(--accent-purple)]" />
                <span className="font-bold">{node.name}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${statusColor[node.status]}`} />
                <span className="text-xs text-[var(--text-secondary)]">{statusLabel[node.status]}</span>
              </div>
            </div>

            <p className="mb-3 text-xs text-[var(--text-secondary)]">{node.model}</p>

            <div className="space-y-2">
              <div>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-[var(--text-secondary)]">
                    <Cpu className="h-3 w-3" /> CPU
                  </span>
                  <span>{node.cpu}%</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
                  <div
                    className="h-1.5 rounded-full bg-[var(--accent-blue)] transition-all"
                    style={{ width: `${node.cpu}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-[var(--text-secondary)]">
                    <MemoryStick className="h-3 w-3" /> MEM
                  </span>
                  <span>{node.memory}%</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
                  <div
                    className="h-1.5 rounded-full bg-[var(--accent-purple)] transition-all"
                    style={{ width: `${node.memory}%` }}
                  />
                </div>
              </div>
            </div>

            {node.browser_layer && (
              <div className="mt-3 flex items-center gap-1 rounded-md bg-[var(--accent-blue)]/10 px-2 py-1 text-xs text-[var(--accent-blue)]">
                <Globe className="h-3 w-3" />
                Browser Layer 有効
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
