'use client';
import { useCallback } from 'react';
import ReactFlow, { Background, Controls, MiniMap, Node, Edge } from 'reactflow';
import 'reactflow/dist/style.css';
import { GraphNode, GraphEdge } from '@/lib/contracts';

export default function ClaimGraph({ nodes, edges }: { nodes: GraphNode[], edges: GraphEdge[] }) {
  const rfNodes: Node[] = nodes.map(n => ({
    id: n.id,
    position: n.position,
    data: n.data,
    type: n.type
  }));

  const rfEdges: Edge[] = edges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label
  }));

  return (
    <div style={{ height: 400, border: '1px solid #e5e7eb', borderRadius: '0.375rem' }}>
      <ReactFlow nodes={rfNodes} edges={rfEdges} fitView>
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
