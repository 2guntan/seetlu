import { createContext, useContext } from "react";

import type { Me } from "../api/client";

export interface AuthState {
  me: Me | undefined;
  loading: boolean;
  signedIn: boolean;
  signIn: (access: string, refresh: string) => void;
  signOut: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
