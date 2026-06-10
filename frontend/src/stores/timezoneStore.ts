import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TimezoneOption } from '../types/common'

interface TimezoneState {
  timezone: TimezoneOption
  setTimezone: (tz: TimezoneOption) => void
}

export const useTimezoneStore = create<TimezoneState>()(
  persist(
    (set) => ({
      timezone: 'America/New_York', // 默认锁定 EST/EDT
      setTimezone: (tz) => set({ timezone: tz }),
    }),
    {
      name: 'msr-timezone',
    },
  ),
)
