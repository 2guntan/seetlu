import { useState } from "react";

import type { Shop } from "../api/client";
import { useAuth } from "./use-auth";

/** The shop picked in the header select (first shop by default), remembered per device. */
export function useShopChoice(): [Shop | undefined, (id: string) => void, Shop[]] {
  const { me } = useAuth();
  const shops = me?.shops ?? [];
  const [id, setId] = useState<string | null>(() => {
    try {
      return localStorage.getItem("seetlu.shop");
    } catch {
      return null;
    }
  });
  const shop = shops.find((s) => s.id === id) ?? shops[0];
  const choose = (v: string) => {
    setId(v);
    try {
      localStorage.setItem("seetlu.shop", v);
    } catch {
      /* ignore */
    }
  };
  return [shop, choose, shops];
}
