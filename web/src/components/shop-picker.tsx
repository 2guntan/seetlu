import { useTranslation } from "react-i18next";

import type { Shop } from "../api/client";

export function ShopPicker({ shop, shops, onChange }: { shop?: Shop; shops: Shop[]; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  if (shops.length < 2) return null;
  return (
    <label className="inline">
      {t("settings.shop")}
      <select value={shop?.id} onChange={(e) => onChange(e.target.value)} name="shop">
        {shops.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </label>
  );
}
