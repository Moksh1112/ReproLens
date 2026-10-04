'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api/client';

export default function UploadPage() {
  const router = useRouter();
  const [paper, setPaper] = useState('');
  const [repo, setRepo] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const assessment = await apiClient.createAssessment(paper, repo);
      await apiClient.runAssessment(assessment.id);
      router.push(`/assessment/${assessment.id}`);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto mt-20 p-6 bg-white border border-gray-200 shadow-sm rounded-md">
      <h1 className="text-2xl font-semibold mb-6">ReproLens Assessment Submission</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Paper (PDF or arXiv ID)</label>
          <input 
            type="text" 
            required 
            className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500" 
            placeholder="e.g. arxiv:1803.03635"
            value={paper}
            onChange={e => setPaper(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Repository (GitHub URL or ZIP)</label>
          <input 
            type="text" 
            required 
            className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500" 
            placeholder="e.g. https://github.com/user/repo"
            value={repo}
            onChange={e => setRepo(e.target.value)}
          />
        </div>
        <button 
          type="submit" 
          disabled={loading}
          className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Submitting...' : 'Start Assessment'}
        </button>
      </form>
    </div>
  );
}
