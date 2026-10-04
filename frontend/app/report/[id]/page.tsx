'use client';
import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api/client';
import { ReportMetadata } from '@/lib/contracts';
import Link from 'next/link';

export default function ReportPage({ params }: { params: { id: string } }) {
  const [report, setReport] = useState<ReportMetadata | null>(null);

  useEffect(() => {
    apiClient.getReport(params.id).then(setReport);
  }, [params.id]);

  if (!report) return <div className="p-8">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto p-6 mt-10 bg-white border shadow-sm rounded">
      <h1 className="text-3xl font-bold mb-6">Generated Report</h1>
      <div className="space-y-4">
        <p><strong>Assessment ID:</strong> {report.assessment_id}</p>
        <p><strong>Generated At:</strong> {new Date(report.generated_at).toLocaleString()}</p>
        <div className="pt-6 flex space-x-4">
          <a href={report.pdf_url} className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">Download PDF</a>
          <a href={report.markdown_url} className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50">Download Markdown</a>
        </div>
        <div className="mt-8">
          <Link href={`/assessment/${params.id}`} className="text-blue-600 hover:underline">← Back to Dashboard</Link>
        </div>
      </div>
    </div>
  );
}
