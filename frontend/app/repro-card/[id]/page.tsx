'use client';
import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api/client';
import { ReproCard } from '@/lib/contracts';
import Link from 'next/link';

export default function ReproCardPage({ params }: { params: { id: string } }) {
  const [card, setCard] = useState<ReproCard | null>(null);

  useEffect(() => {
    apiClient.getReproCard(params.id).then(setCard);
  }, [params.id]);

  if (!card) return <div className="p-8">Loading...</div>;

  return (
    <div className="max-w-2xl mx-auto p-6 mt-10">
      <div className="bg-white border-2 border-gray-900 rounded-lg shadow-xl overflow-hidden">
        
        {/* Header section */}
        <div className="bg-gray-900 text-white p-6 text-center">
          <h1 className="text-sm uppercase tracking-widest font-semibold text-gray-300 mb-2">Repro Card</h1>
          <h2 className="text-2xl font-bold">{card.paper_title}</h2>
        </div>

        {/* Scores Grid */}
        <div className="grid grid-cols-2 divide-x divide-gray-200 border-b border-gray-200">
          <div className="p-6 text-center">
            <div className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Repro Score</div>
            <div className="mt-2 text-4xl font-extrabold text-blue-600">
              {card.repro_score !== undefined ? card.repro_score.toFixed(1) : '--'}
            </div>
            <div className="text-xs text-gray-400 mt-1">/ 100</div>
          </div>
          <div className="p-6 text-center">
            <div className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Coverage</div>
            <div className="mt-2 text-4xl font-extrabold text-green-600">
              {card.coverage !== undefined ? (card.coverage * 100).toFixed(0) : '--'}%
            </div>
            <div className="text-xs text-gray-400 mt-1">Claims Testable</div>
          </div>
        </div>


        {/* Environment section */}
        <div className="p-6 bg-gray-50">
          <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">Environment Lockfile</h3>
          <pre className="text-xs text-gray-600 bg-gray-200 p-3 rounded font-mono overflow-x-auto">
            {card.environment_lockfile}
          </pre>
        </div>

        {/* Discrepancies */}
        {card.top_discrepancies.length > 0 && (
          <div className="p-6 border-t border-gray-200">
            <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">Top Discrepancies</h3>
            <ul className="space-y-2 text-sm text-gray-700">
              {card.top_discrepancies.map((d, i) => (
                <li key={i}>Claim {d.claim_id}: {d.gap} gap</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="mt-8 text-center">
        <Link href={`/assessment/${params.id}`} className="text-blue-600 hover:underline">← Back to Dashboard</Link>
      </div>
    </div>
  );
}
