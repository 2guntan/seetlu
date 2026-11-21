import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import fr from "./fr.json";
import wo from "./wo.json";

export const languages = ["fr", "wo", "en"] as const;
export type Language = (typeof languages)[number];
const KEY = "seetlu.lang";

function saved(): Language {
  try {
    const v = localStorage.getItem(KEY);
    return (languages as readonly string[]).includes(v ?? "") ? (v as Language) : "fr";
  } catch {
    return "fr";
  }
}

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, wo: { translation: wo }, en: { translation: en } },
  lng: saved(),
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: Language): void {
  try {
    localStorage.setItem(KEY, lang);
  } catch {
    /* private mode */
  }
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
}

export default i18n;
