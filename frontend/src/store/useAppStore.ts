import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { ChatResponse } from '@/types/api';

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  response?: ChatResponse;
  timestamp: string;
  questionLang?: 'ar' | 'en';
}

interface AppState {
  sessionId: string | null;
  activeDatabase: string | null;
  activeDatabaseType: string | null;
  theme: 'light' | 'dark';
  chatMessages: ChatMessage[];
  setSessionId: (id: string) => void;
  setActiveDatabase: (db: string, type: string) => void;
  toggleTheme: () => void;
  setChatMessages: (messages: ChatMessage[] | ((messages: ChatMessage[]) => ChatMessage[])) => void;
  clearChatMessages: () => void;
}

export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set) => ({
        sessionId: null,
        activeDatabase: null,
        activeDatabaseType: null,
        theme: 'dark', // Dark mode by default
        chatMessages: [],
        setSessionId: (id) => set({ sessionId: id }),
        setActiveDatabase: (db, type) => set({ activeDatabase: db, activeDatabaseType: type }),
        toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
        setChatMessages: (messages) => set((state) => ({
          chatMessages: typeof messages === 'function' ? messages(state.chatMessages) : messages,
        })),
        clearChatMessages: () => set({ chatMessages: [] }),
      }),
      {
        name: 'ai-db-analyst-storage',
      }
    )
  )
);
