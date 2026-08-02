import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

interface AppState {
  sessionId: string | null;
  activeDatabase: string | null;
  activeDatabaseType: string | null;
  theme: 'light' | 'dark';
  setSessionId: (id: string) => void;
  setActiveDatabase: (db: string, type: string) => void;
  toggleTheme: () => void;
}

export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set) => ({
        sessionId: null,
        activeDatabase: null,
        activeDatabaseType: null,
        theme: 'dark', // Dark mode by default
        setSessionId: (id) => set({ sessionId: id }),
        setActiveDatabase: (db, type) => set({ activeDatabase: db, activeDatabaseType: type }),
        toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
      }),
      {
        name: 'ai-db-analyst-storage',
      }
    )
  )
);
