import React, { useState } from 'react';
import { api } from './api';
import { LogIn, Upload, ShieldAlert, FileSpreadsheet, CheckCircle2, AlertTriangle, Download, LogOut, ShieldCheck, Sparkles, ArrowUpRight } from 'lucide-react';

export default function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [role, setRole] = useState<string | null>(localStorage.getItem('role'));
  
  // Auth Form State
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Dashboard State
  const [file, setFile] = useState<File | null>(null);
  const [origin, setOrigin] = useState<'synthetic' | 'real'>('synthetic');
  const [uploading, setUploading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [runResults, setRunResults] = useState<any | null>(null);
  const [statusMessage, setStatusMessage] = useState('');

  // Login handler
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError('');
    try {
      const res = await api.post('/auth/login', { username, password });
      const { access_token, role: userRole } = res.data;
      localStorage.setItem('token', access_token);
      localStorage.setItem('role', userRole);
      setToken(access_token);
      setRole(userRole);
    } catch (err: any) {
      setAuthError(err.response?.data?.detail || 'Login failed');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    setToken(null);
    setRole(null);
    setRunResults(null);
    setDatasetId(null);
  };

  // Upload handler
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setStatusMessage('Uploading and validating structure...');
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('data_origin', origin);

      const res = await api.post('/datasets', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const newId = res.data.id || res.data.dataset_id || res.data.pk;
      setDatasetId(newId);
      setStatusMessage(`Dataset uploaded successfully (ID: ${newId}). Ready for evaluation.`);
    } catch (err: any) {
      setStatusMessage(`Upload failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setUploading(false);
    }
  };

  // Evaluate handler
  const handleEvaluate = async () => {
    if (!datasetId) return;
    setEvaluating(true);
    setStatusMessage('Running 9 deterministic metric checks...');
    try {
      const evalRes = await api.post(`/datasets/${datasetId}/evaluate`);
      const runId = evalRes.data.run_id || evalRes.data.id || datasetId;

      let runDetails = {};
      try {
        const runRes = await api.get(`/runs/${runId}`);
        runDetails = runRes.data;
      } catch (err) {
        console.log('Could not fetch separate run details, using evaluation response');
      }

      setRunResults({ ...evalRes.data, ...runDetails, id: runId });
      setStatusMessage('Evaluation complete!');
    } catch (err: any) {
      setStatusMessage(`Evaluation failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setEvaluating(false);
    }
  };

  // Export report
  const handleExport = async () => {
    const runId = runResults?.id || datasetId;
    if (!runId) return;
    try {
      const res = await api.get(`/runs/${runId}/report.csv`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `run_${runId}_report.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err: any) {
      alert(`Export failed: ${err.response?.data?.detail || err.message}`);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-indigo-50/30 to-slate-100 text-slate-900 flex items-center justify-center p-4">
        <div className="bg-white/90 backdrop-blur-xl p-8 rounded-3xl border border-slate-200/80 w-full max-w-md shadow-2xl shadow-indigo-500/10">
          <div className="flex items-center gap-3.5 mb-6">
            <div className="p-3 bg-indigo-600 text-white rounded-2xl shadow-lg shadow-indigo-600/30">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-extrabold tracking-tight text-slate-900">Enterprise Portal</h1>
              <p className="text-xs text-slate-500 font-medium">Insurance Integrity Audit Engine</p>
            </div>
          </div>
          {authError && (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3.5 rounded-2xl mb-5 text-xs font-semibold flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-600"></span> {authError}
            </div>
          )}
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Username</label>
              <input
                type="text"
                className="w-full bg-slate-50/80 border border-slate-200 rounded-2xl px-4 py-3 text-slate-900 text-sm focus:outline-none focus:border-indigo-600 focus:bg-white transition-all shadow-2xs"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter admin username"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Password</label>
              <input
                type="password"
                className="w-full bg-slate-50/80 border border-slate-200 rounded-2xl px-4 py-3 text-slate-900 text-sm focus:outline-none focus:border-indigo-600 focus:bg-white transition-all shadow-2xs"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>
            <button
              type="submit"
              className="w-full bg-indigo-600 hover:bg-indigo-700 font-bold py-3.5 px-4 rounded-2xl transition-all flex items-center justify-center gap-2 text-white text-sm shadow-xl shadow-indigo-600/25 cursor-pointer mt-2"
            >
              <LogIn className="w-4 h-4" /> Sign In to Dashboard
            </button>
          </form>
        </div>
      </div>
    );
  }

  const dataObj = runResults?.data || runResults?.results || runResults;
  const observationsList = dataObj?.observations || dataObj?.findings || dataObj?.issues || dataObj?.metrics || dataObj?.rule_results || dataObj?.checks || [];
  const healthScore = dataObj?.overall_score ?? dataObj?.summary_score ?? dataObj?.score ?? dataObj?.health_score ?? 'N/A';
  const totalClaimsCount = dataObj?.kpis?.total_claims ?? dataObj?.total_claims ?? dataObj?.claims_evaluated ?? dataObj?.total ?? dataObj?.record_count ?? dataObj?.total_records ?? dataObj?.claim_count ?? dataObj?.num_claims ?? dataObj?.row_count ?? 0;
  
  const numericScore = typeof healthScore === 'number' ? healthScore : parseFloat(healthScore);
  const isPassing = !isNaN(numericScore) && numericScore > 59.0;
  const strokeDashoffset = !isNaN(numericScore) ? 283 - (283 * Math.min(numericScore, 100)) / 100 : 283;

  return (
    <div className="min-h-screen bg-slate-50/70 text-slate-900 font-sans antialiased selection:bg-indigo-600 selection:text-white">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-200/80 bg-white/80 backdrop-blur-xl px-8 py-4 flex items-center justify-between sticky top-0 z-50 shadow-xs">
        <div className="flex items-center gap-3.5">
          <div className="p-2.5 bg-gradient-to-tr from-indigo-600 to-indigo-500 text-white rounded-2xl shadow-md shadow-indigo-500/20">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-extrabold text-slate-900 tracking-tight">Insurance Claim Integrity Audit</h1>
              <span className="bg-indigo-50 text-indigo-700 text-[10px] font-bold px-2 py-0.5 rounded-full border border-indigo-200/60 uppercase tracking-wide">v2.4 Live</span>
            </div>
            <p className="text-xs text-slate-500 font-medium">Deterministic Compliance & Risk Engine</p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="hidden sm:flex items-center gap-2 bg-slate-100/80 border border-slate-200/80 px-3.5 py-1.5 rounded-full text-xs font-semibold text-slate-700">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Role: <span className="text-indigo-600 uppercase tracking-wide font-bold">{role}</span>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-slate-600 hover:text-slate-900 font-bold text-xs px-3.5 py-2 rounded-xl border border-slate-200 hover:bg-slate-100/80 transition-all cursor-pointer shadow-2xs"
          >
            <LogOut className="w-3.5 h-3.5 text-slate-400" /> Logout
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-8 space-y-8">
        {/* Upload Card Section */}
        <div className="bg-white border border-slate-200/80 rounded-3xl p-8 shadow-xl shadow-slate-200/50 relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-br from-indigo-500/5 via-purple-500/5 to-transparent rounded-full blur-3xl pointer-events-none"></div>
          
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-base font-extrabold text-slate-900 flex items-center gap-2.5">
              <div className="p-2 bg-indigo-50 text-indigo-600 rounded-xl">
                <Upload className="w-4 h-4" />
              </div>
              Dataset Pipeline & Ingestion
            </h2>
            <span className="text-xs font-semibold text-slate-400">Step 1 of 2</span>
          </div>

          <form onSubmit={handleUpload} className="grid grid-cols-1 md:grid-cols-12 gap-5 items-end">
            <div className="md:col-span-5">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Source CSV / Excel File</label>
              <label className="flex items-center justify-between px-4 py-3.5 bg-slate-50/80 border border-slate-200 rounded-2xl cursor-pointer hover:border-indigo-600 transition-all shadow-2xs group">
                <span className="text-sm font-medium text-slate-600 truncate">
                  {file ? file.name : 'Choose dataset file...'}
                </span>
                <span className="text-xs font-bold text-indigo-600 bg-indigo-50 group-hover:bg-indigo-100 px-3 py-1.5 rounded-xl transition-all">
                  Browse
                </span>
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="hidden"
                  required
                />
              </label>
            </div>
            
            <div className="md:col-span-4">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Data Origin Standard</label>
              <select
                value={origin}
                onChange={(e: any) => setOrigin(e.target.value)}
                className="w-full bg-slate-50/80 border border-slate-200 rounded-2xl px-4 py-3.5 text-slate-900 text-sm font-medium focus:outline-none focus:border-indigo-600 transition-all shadow-2xs"
              >
                <option value="synthetic">Synthetic (Permitted)</option>
                <option value="real">Real Production (Strict Gating)</option>
              </select>
            </div>

            <div className="md:col-span-3">
              <button
                type="submit"
                disabled={uploading || !file}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 py-3.5 px-5 rounded-2xl font-bold text-white text-sm transition-all flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/25 cursor-pointer"
              >
                <FileSpreadsheet className="w-4 h-4" /> {uploading ? 'Uploading...' : 'Upload Dataset'}
              </button>
            </div>
          </form>

          {datasetId && (
            <div className="mt-6 pt-5 border-t border-slate-100 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50/80 border border-emerald-200/80 px-4 py-2 rounded-2xl font-bold">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" /> Dataset #{datasetId} Staged & Validated Successfully
              </div>
              <button
                onClick={handleEvaluate}
                disabled={evaluating}
                className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 px-6 py-3 rounded-2xl font-bold text-white text-xs uppercase tracking-wider transition-all shadow-lg shadow-emerald-600/20 cursor-pointer flex items-center justify-center gap-2"
              >
                <Sparkles className="w-4 h-4" /> {evaluating ? 'Executing Rules...' : 'Run Deterministic Metric Evaluation'}
              </button>
            </div>
          )}

          {statusMessage && (
            <div className="mt-4 text-xs font-semibold text-slate-600 bg-slate-50 p-3.5 rounded-2xl border border-slate-200/80 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-600 animate-ping"></span>
              {statusMessage}
            </div>
          )}
        </div>

        {/* Evaluation Summary Results */}
        {runResults && (
          <div className="space-y-8 animate-fade-in">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Overall Health Score Card */}
              <div className="bg-white border border-slate-200/80 p-7 rounded-3xl shadow-xl shadow-slate-200/50 flex flex-col justify-between relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 rounded-bl-full pointer-events-none"></div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs uppercase font-extrabold text-slate-400 tracking-wider">Overall Health Score</p>
                    {isPassing ? (
                      <span className="p-1.5 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-100">
                        <ShieldCheck className="w-4 h-4" />
                      </span>
                    ) : (
                      <span className="p-1.5 bg-amber-50 text-amber-600 rounded-xl border border-amber-100">
                        <ShieldAlert className="w-4 h-4" />
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400">Deterministic Threshold: 59.0% Cap</p>
                </div>

                <div className="my-5 flex items-center justify-between">
                  <div className="space-y-1">
                    <div className={`text-4xl font-black tracking-tight ${isPassing ? 'text-emerald-600' : 'text-amber-600'}`}>
                      {typeof healthScore === 'number' ? `${healthScore.toFixed(2)}%` : `${healthScore}%`}
                    </div>
                  </div>

                  {/* SVG Circular Progress Dial */}
                  <div className="relative w-20 h-20 flex items-center justify-center">
                    <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                      <circle
                        cx="50"
                        cy="50"
                        r="45"
                        className="text-slate-100 stroke-current"
                        strokeWidth="10"
                        fill="transparent"
                      />
                      <circle
                        cx="50"
                        cy="50"
                        r="45"
                        className={`stroke-current transition-all duration-1000 ease-out ${
                          isPassing ? 'text-emerald-500' : 'text-amber-500'
                        }`}
                        strokeWidth="10"
                        strokeDasharray="283"
                        strokeDashoffset={strokeDashoffset}
                        strokeLinecap="round"
                        fill="transparent"
                      />
                    </svg>
                  </div>
                </div>

                <div>
                  {runResults.gating_applied || !isPassing ? (
                    <span className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-800 border border-amber-200/85 text-xs px-3.5 py-1.5 rounded-xl font-bold">
                      ▲ Capped by Safety Guardrail (≤59%)
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 bg-emerald-50 text-emerald-700 border border-emerald-200/85 text-xs px-3.5 py-1.5 rounded-xl font-bold">
                      ● Passing Enterprise Standard
                    </span>
                  )}
                </div>
              </div>

              {/* Total Claims Evaluated Card */}
              <div className="bg-white border border-slate-200/80 p-7 rounded-3xl shadow-xl shadow-slate-200/50 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs uppercase font-extrabold text-slate-400 tracking-wider">Claims Evaluated</p>
                    <span className="p-1.5 bg-blue-50 text-blue-600 rounded-xl border border-blue-100">
                      <FileSpreadsheet className="w-4 h-4" />
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">Active verification batch</p>
                </div>
                <div className="my-5">
                  <div className="text-4xl font-black text-slate-900 tracking-tight">
                    {totalClaimsCount.toLocaleString()}
                  </div>
                  <p className="text-xs text-slate-500 mt-1 font-medium">Fully processed through 9 audit checks</p>
                </div>
                <div className="text-xs font-bold text-indigo-600 flex items-center gap-1">
                  Verified Data Registry <ArrowUpRight className="w-3.5 h-3.5" />
                </div>
              </div>

              {/* Export Report Card */}
              <div className="bg-white border border-slate-200/80 p-7 rounded-3xl shadow-xl shadow-slate-200/50 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs uppercase font-extrabold text-slate-400 tracking-wider">Audit Report</p>
                    <span className="p-1.5 bg-purple-50 text-purple-600 rounded-xl border border-purple-100">
                      <Download className="w-4 h-4" />
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">Compliant external release</p>
                </div>
                <div className="my-5">
                  <p className="text-xs font-semibold text-slate-600 leading-relaxed">
                    Automatically sanitizes and strips sensitive PII and financial evidence for external review.
                  </p>
                </div>
                <button
                  onClick={handleExport}
                  className="w-full bg-slate-900 hover:bg-slate-800 text-white font-bold py-3.5 px-4 rounded-2xl text-xs uppercase tracking-wider transition-all flex items-center justify-center gap-2 shadow-lg shadow-slate-900/20 cursor-pointer"
                >
                  <Download className="w-4 h-4" /> Download Safe Audit Report
                </button>
              </div>
            </div>

            {/* Observations Table */}
            <div className="bg-white border border-slate-200/80 rounded-3xl p-8 shadow-xl shadow-slate-200/50">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-base font-extrabold text-slate-900 flex items-center gap-2.5">
                  <div className="p-2 bg-amber-50 text-amber-600 rounded-xl">
                    <AlertTriangle className="w-4 h-4" />
                  </div>
                  Traceable Observations & Recommendations
                </h3>
                <span className="bg-slate-100 text-slate-600 text-xs font-bold px-3 py-1 rounded-full border border-slate-200">
                  {observationsList.length} Findings Logged
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 text-slate-400 text-[11px] font-black uppercase tracking-wider">
                      <th className="py-3.5 px-4">Severity Level</th>
                      <th className="py-3.5 px-4">Compliance Issue</th>
                      <th className="py-3.5 px-4">Recorded Evidence</th>
                      <th className="py-3.5 px-4">Corrective Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {observationsList.map((obs: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-4 px-4 align-top">
                          <span
                            className={`px-3 py-1 rounded-full text-xs font-extrabold tracking-wide inline-flex items-center gap-1.5 ${
                              (obs.severity || '').toLowerCase() === 'critical'
                                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                                : (obs.severity || '').toLowerCase() === 'warning'
                                ? 'bg-amber-50 text-amber-800 border border-amber-200'
                                : 'bg-slate-100 text-slate-700 border border-slate-200'
                            }`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              (obs.severity || '').toLowerCase() === 'critical' ? 'bg-rose-600' :
                              (obs.severity || '').toLowerCase() === 'warning' ? 'bg-amber-600' : 'bg-slate-500'
                            }`}></span>
                            {obs.severity || 'info'}
                          </span>
                        </td>
                        <td className="py-4 px-4 font-bold text-slate-900 align-top">{obs.issue || obs.metric_name || obs.name}</td>
                        <td className="py-4 px-4 text-slate-600 font-mono text-xs align-top bg-slate-50/50 rounded-xl my-1">{obs.evidence || obs.details || obs.description}</td>
                        <td className="py-4 px-4 text-slate-700 font-medium align-top">{obs.recommendation || obs.action || 'Review claim records'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}