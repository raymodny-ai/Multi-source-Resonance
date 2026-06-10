import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  refreshToken: string | null
  username: string | null
  setAuth: (token: string, refreshToken?: string, username?: string) => void
  logout: () => void
  isAuthenticated: () => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      username: null,
      setAuth: (token, refreshToken, username) =>
        set({ token, refreshToken: refreshToken ?? null, username: username ?? null }),
      logout: () => set({ token: null, refreshToken: null, username: null }),
      isAuthenticated: () => !!get().token,
    }),
    {
      name: 'msr-auth',
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
        username: state.username,
      }),
    },
  ),
)
