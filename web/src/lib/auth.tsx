import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { get, setLogoutHandler, tokens, type Me } from "../api/client";
import { AuthContext, type AuthState } from "./use-auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(() => tokens.access !== null);
  const signOut = useCallback(() => {
    tokens.clear();
    qc.clear();
    setSignedIn(false);
  }, [qc]);
  useEffect(() => setLogoutHandler(signOut), [signOut]);
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/v1/me"), enabled: signedIn });
  const value = useMemo<AuthState>(
    () => ({
      me: me.data,
      loading: signedIn && me.isPending,
      signedIn,
      signIn: (access, refresh) => {
        tokens.set(access, refresh);
        setSignedIn(true);
      },
      signOut,
    }),
    [me.data, me.isPending, signedIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
