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
  chatSessionsData: Record<string, ChatMessage[]>;
  setSessionId: (id: string) => void;
  setActiveDatabase: (db: string, type: string) => void;
  toggleTheme: () => void;
  setChatMessages: (messages: ChatMessage[] | ((messages: ChatMessage[]) => ChatMessage[])) => void;
  clearChatMessages: () => void;
}

export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set, get) => ({
        sessionId: null,
        activeDatabase: null,
        activeDatabaseType: null,
        theme: 'dark', // Dark mode by default
        chatSessionsData: {},
        setSessionId: (id) => set({ sessionId: id }),
        setActiveDatabase: (db, type) => set({ activeDatabase: db, activeDatabaseType: type }),
        toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
        setChatMessages: (messages) => set((state) => {
          const sid = state.sessionId || "default_session";
          const currentMsgs = state.chatSessionsData[sid] || [];
          const newMsgs = typeof messages === 'function' ? messages(currentMsgs) : messages;
          return {
            chatSessionsData: {
              ...state.chatSessionsData,
              [sid]: newMsgs
            }
          };
        }),
        clearChatMessages: () => set((state) => {
          const sid = state.sessionId || "default_session";
          return {
            chatSessionsData: {
              ...state.chatSessionsData,
              [sid]: []
            }
          };
        }),
      }),
      {
        name: 'ai-db-analyst-storage',
      }
    )
  )
);
