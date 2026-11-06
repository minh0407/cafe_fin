import { create } from "zustand";
import type { BootSession, User } from "./types";
interface SessionState {
  boot: BootSession | null;
  token: string | null;
  user: User | null;
  connected: boolean;
  setBoot: (boot: BootSession) => void;
  login: (token: string, user: User) => void;
  logout: () => void;
  connection: (connected: boolean) => void;
  reset: () => void;
}
// Intentionally no persist middleware: app/user credentials live only in memory.
export const useSession = create<SessionState>((set) => ({
  boot: null,
  token: null,
  user: null,
  connected: false,
  setBoot: (boot) => set({ boot, token: null, user: null, connected: true }),
  login: (token, user) => set({ token, user }),
  logout: () => set({ token: null, user: null }),
  connection: (connected) => set({ connected }),
  reset: () => set({ boot: null, token: null, user: null, connected: false }),
}));
