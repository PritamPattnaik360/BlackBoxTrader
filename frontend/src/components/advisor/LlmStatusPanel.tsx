import { useQuery } from '@tanstack/react-query'
import { Brain, CheckCircle, XCircle, Download } from 'lucide-react'
import api from '../../api/client'

interface LlmStatus {
  ollama_running: boolean
  models: string[]
  default_model: string
  recommended_model: string
  pull_command: string
}

interface TrainingStats {
  total_samples: number
  win_samples: number
  high_quality: number
  ready_to_train: boolean
  recent: Array<{ ticker: string; source: string; quality: number }>
}

export default function LlmStatusPanel() {
  const { data: status } = useQuery<LlmStatus>({
    queryKey: ['llmStatus'],
    queryFn: () => api.get('/advisor/status').then(r => r.data),
    refetchInterval: 15_000,
  })
  const { data: training } = useQuery<TrainingStats>({
    queryKey: ['trainingStats'],
    queryFn: () => api.get('/advisor/training').then(r => r.data),
    refetchInterval: 30_000,
  })

  const running = status?.ollama_running ?? false

  return (
    <div className="space-y-4">
      <div className="text-sm font-medium flex items-center gap-2">
        <Brain size={15} className="text-purple-400" />
        Local LLM Trading Signal
      </div>

      {/* Ollama status */}
      <div className={`rounded-lg border p-3 ${running ? 'border-green-700 bg-green-900/20' : 'border-gray-700 bg-gray-800/50'}`}>
        <div className="flex items-center gap-2 mb-1">
          {running
            ? <CheckCircle size={13} className="text-green-400" />
            : <XCircle size={13} className="text-gray-500" />}
          <span className={`text-sm font-medium ${running ? 'text-green-300' : 'text-gray-400'}`}>
            {running ? 'LLM Active — contributing to signals' : 'LLM Offline — signals use 4-factor model'}
          </span>
        </div>
        {running && status?.models && status.models.length > 0 && (
          <div className="text-xs text-gray-400 mt-1">
            Models: {status.models.join(', ')}
          </div>
        )}
        {!running && (
          <div className="text-xs text-gray-500 mt-2 space-y-1">
            <div>To enable the LLM signal (5th alpha source, 20% weight):</div>
            <div className="bg-gray-900 rounded px-2 py-1 font-mono text-gray-300">
              1. Download Ollama from ollama.com/download
            </div>
            <div className="bg-gray-900 rounded px-2 py-1 font-mono text-gray-300">
              2. Run: ollama pull llama3.2:3b
            </div>
            <div className="text-gray-500">Ollama starts automatically. BlackBoxTrader detects it instantly.</div>
          </div>
        )}
      </div>

      {/* Training data */}
      <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-3">
        <div className="text-xs font-medium text-gray-400 mb-2">Training Data (stored in local DB)</div>
        <div className="grid grid-cols-3 gap-3 text-center mb-3">
          <div>
            <div className="text-lg font-bold text-white">{training?.total_samples ?? 0}</div>
            <div className="text-xs text-gray-500">Total samples</div>
          </div>
          <div>
            <div className="text-lg font-bold text-green-400">{training?.high_quality ?? 0}</div>
            <div className="text-xs text-gray-500">High quality</div>
          </div>
          <div>
            <div className="text-lg font-bold text-blue-400">{training?.win_samples ?? 0}</div>
            <div className="text-xs text-gray-500">Win trades</div>
          </div>
        </div>

        {training?.ready_to_train ? (
          <div className="text-xs text-green-400 text-center">
            Ready to fine-tune! Run: <code className="bg-gray-900 px-1 rounded">python scripts/finetune_llm.py</code>
          </div>
        ) : (
          <div className="text-xs text-gray-500 text-center">
            Need {Math.max(0, 50 - (training?.total_samples ?? 0))} more trades to unlock fine-tuning.
            Samples collect automatically as BlackBoxTrader trades.
          </div>
        )}

        {training?.recent && training.recent.length > 0 && (
          <div className="mt-3 space-y-1">
            <div className="text-xs text-gray-500">Recent samples:</div>
            {training.recent.map((s, i) => (
              <div key={i} className="flex justify-between text-xs text-gray-400">
                <span>{s.ticker}</span>
                <span className="text-gray-500">{s.source}</span>
                <span className={s.quality >= 0.7 ? 'text-green-400' : 'text-gray-400'}>
                  q={s.quality.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        )}

        <a
          href="/api/v1/advisor/training/export"
          download="blackbox_training_data.jsonl"
          className="mt-3 flex items-center justify-center gap-2 text-xs text-blue-400 hover:text-blue-300"
        >
          <Download size={11} /> Export training data (JSONL)
        </a>
      </div>

      <div className="text-xs text-gray-500">
        How it works: every closed trade is saved as a training example.
        Once you have 50+ samples, run <code className="bg-gray-800 px-1 rounded">python scripts/finetune_llm.py</code> to
        fine-tune a local model that gets progressively better at predicting profitable trades.
      </div>
    </div>
  )
}
