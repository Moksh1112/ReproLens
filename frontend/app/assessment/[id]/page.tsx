'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api/client';
import { AssessmentSummary, StageProgress, Verdict, Discrepancy, AuditItem, GraphNode, GraphEdge } from '@/lib/contracts';
import ClaimGraph from '@/components/ClaimGraph';
import Link from 'next/link';

export default function AssessmentDashboard({ params }: { params: { id: string } }) {
  const [assessment, setAssessment] = useState<AssessmentSummary | null>(null);
  const [progress, setProgress] = useState<StageProgress[]>([]);
  const [verdicts, setVerdicts] = useState<Verdict[]>([]);
  const [discrepancies, setDiscrepancies] = useState<Discrepancy[]>([]);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [graphData, setGraphData] = useState<{nodes: GraphNode[], edges: GraphEdge[]} | null>(null);

  useEffect(() => {
    async function load() {
      setAssessment(await apiClient.getAssessment(params.id));
      setProgress(await apiClient.getStageProgress(params.id));
      setVerdicts(await apiClient.getVerdicts(params.id));
      setDiscrepancies(await apiClient.getDiscrepancies(params.id));
      setAudit(await apiClient.getAudit(params.id));
      setGraphData(await apiClient.getClaimGraph(params.id));
    }
    load();
  }, [params.id]);

  if (!assessment) return <div className="p-8">Loading...</div>;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8">
      
      {/* Header */}
      <header className="border-b pb-4">
        <h1 className="text-3xl font-bold">Assessment Dashboard</h1>
        <p className="text-gray-600 mt-2">ID: {assessment.id}</p>
        <div className="mt-4 flex space-x-4">
          <Link href={`/report/${assessment.id}`} className="text-blue-600 hover:underline">View Report</Link>
          <Link href={`/repro-card/${assessment.id}`} className="text-blue-600 hover:underline">View Repro Card</Link>
        </div>
      </header>

      {/* Progress */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Pipeline Progress</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {progress.map((p, i) => (
            <div key={i} className="p-4 border rounded shadow-sm bg-white">
              <div className="font-medium">{p.stage_name}</div>
              <div className="text-sm text-gray-500 capitalize">{p.status}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Verdict Table */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Verdict Table</h2>
        <div className="overflow-x-auto border rounded bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left font-medium text-gray-500">Claim ID</th>
                <th className="px-6 py-3 text-left font-medium text-gray-500">Reported</th>
                <th className="px-6 py-3 text-left font-medium text-gray-500">Reproduced</th>
                <th className="px-6 py-3 text-left font-medium text-gray-500">Tolerance</th>
                <th className="px-6 py-3 text-left font-medium text-gray-500">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {verdicts.map((v, i) => (
                <tr key={i}>
                  <td className="px-6 py-4">{v.claim_id}</td>
                  <td className="px-6 py-4">{v.reported_value}</td>
                  <td className="px-6 py-4">{v.reproduced_mean.toFixed(2)} ± {v.reproduced_std.toFixed(2)}</td>
                  <td className="px-6 py-4">{v.tolerance}</td>
                  <td className="px-6 py-4 font-semibold">{v.verdict}</td>
                </tr>
              ))}
              {verdicts.length === 0 && (
                <tr><td colSpan={5} className="px-6 py-4 text-center text-gray-500">No verdicts yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Discrepancies */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Discrepancy Detective</h2>
        {discrepancies.length === 0 ? (
          <p className="text-gray-500">No major discrepancies detected.</p>
        ) : (
          <div className="space-y-4">
            {discrepancies.map((d, i) => (
              <div key={i} className="p-4 border rounded bg-white shadow-sm">
                <div className="font-semibold text-lg mb-2">Claim ID: {d.claim_id} (Gap: {d.gap})</div>
                <ul className="list-disc pl-5 space-y-1">
                  {d.causes.map((c, j) => (
                    <li key={j}>
                      <strong>{c.setting_name}</strong>: Paper stated "{c.paper_value}", Run used "{c.actual_value}" 
                      <span className="ml-2 text-xs px-2 py-1 bg-gray-100 rounded">{c.status}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Audit Panel */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Checklist Audit</h2>
        <div className="grid gap-4">
          {audit.map((a, i) => (
            <div key={i} className="p-4 border rounded bg-white shadow-sm flex items-start justify-between">
              <div>
                <div className="font-medium text-lg">{a.topic}</div>
                <div className="text-sm text-gray-600 mt-1">{a.explanation}</div>
                {a.evidence && <div className="text-sm text-gray-500 mt-2 bg-gray-50 p-2 italic">Evidence: {a.evidence}</div>}
              </div>
              <div className={`px-3 py-1 rounded text-sm font-semibold 
                ${a.status === 'Stated' ? 'bg-green-100 text-green-800' : 
                  a.status === 'Missing' ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'}`}>
                {a.status}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Claim Graph */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Claim Graph</h2>
        {graphData ? (
          <ClaimGraph nodes={graphData.nodes} edges={graphData.edges} />
        ) : (
          <p className="text-gray-500">Loading graph...</p>
        )}
      </section>

      {/* Logs View Placeholder */}
      <section>
        <h2 className="text-xl font-semibold mb-4">Execution Logs</h2>
        <div className="p-4 bg-gray-900 text-gray-100 rounded overflow-x-auto text-sm font-mono whitespace-pre-wrap">
          {/* Logs will be streamed here from backend artifacts */}
          [2026-10-04 12:00:00] Worker started...
          [2026-10-04 12:00:05] Running mock environment...
          [2026-10-04 12:00:10] Executing seed 1... completed.
          [2026-10-04 12:00:15] Executing seed 2... completed.
          [2026-10-04 12:00:20] Executing seed 3... completed.
        </div>
      </section>

    </div>
  );
}
