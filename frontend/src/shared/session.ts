import { create } from "zustand";
import type { BootSession, MaintenanceView, User } from "./types";
interface SessionState {
  boot: BootSession | null;
  token: string | null;
  user: User | null;
  connected: boolean;
  generation: number;
  generationSignal: AbortSignal;
  maintenance: { operation: MaintenanceView | null; uncertain: boolean; beginUncertain: boolean };
  maintenanceState: (patch: Partial<SessionState["maintenance"]>) => void;
  // Metadata only; never establishes a new child/session or changes the actor.
  bootMetadata: (generation: number, nativeGeneration: string, patch: Pick<BootSession, "runtime_state" | "pending_transition">) => void;
  setBoot: (boot: BootSession) => void;
  login: (token: string, user: User) => void;
  logout: () => void;
  connection: (connected: boolean) => void;
  reset: () => void;
}
// Intentionally no persist middleware: app/user credentials live only in memory.
export const useSession = create<SessionState>((set) => {
  let controller = new AbortController();
  const advance = (patch: Partial<SessionState>) => {
    const previous = controller;
    controller = new AbortController();
    // Publish the new identity before abort listeners run. An old rejection must
    // observe its stale generation instead of changing the new actor's state.
    set((state) => ({
      ...patch,
      generation: state.generation + 1,
      generationSignal: controller.signal,
    }));
    previous.abort();
  };
  return {
    boot: null,
    token: null,
    user: null,
    connected: false,
    generation: 0,
    generationSignal: controller.signal,
    maintenance: { operation: null, uncertain: false, beginUncertain: false },
    maintenanceState: (patch) => set((state) => ({ maintenance: { ...state.maintenance, ...patch } })),
    bootMetadata: (generation, nativeGeneration, patch) => set((state) =>
      state.generation === generation && state.boot?.generation === nativeGeneration
        ? { boot: { ...state.boot, ...patch } } : {}),
    setBoot: (boot) =>
      advance({ boot, token: null, user: null, connected: true,
        maintenance: { operation: null, uncertain: false, beginUncertain: false } }),
    login: (token, user) => advance({ token, user }),
    logout: () => advance({ token: null, user: null }),
    connection: (connected) => set({ connected }),
    reset: () =>
      advance({ boot: null, token: null, user: null, connected: false,
        maintenance: { operation: null, uncertain: false, beginUncertain: false } }),
  };
});
