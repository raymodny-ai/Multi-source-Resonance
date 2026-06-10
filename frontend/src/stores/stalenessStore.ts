import { create } from 'zustand'

interface SourceTimestamp {
  source: string
  lastUpdatedAt: number // milliseconds since epoch
}

interface StalenessState {
  sources: Record<string, number>
  updateSource: (source: string, timestamp?: number) => void
  getLastUpdated: (source: string) => number | null
}

export const useStalenessStore = create<StalenessState>()((set, get) => ({
  sources: {},
  updateSource: (source, timestamp) =>
    set((state) => ({
      sources: {
        ...state.sources,
        [source]: timestamp ?? Date.now(),
      },
    })),
  getLastUpdated: (source) => get().sources[source] ?? null,
}))
