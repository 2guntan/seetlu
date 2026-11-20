import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import fr from "./fr.json";
import wo from "./wo.json";

export const languages = ["fr", "wo", "en"] as const;
export type Language = (typeof languages)[number];

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, wo: { translation: wo }, en: { translation: en } },
  lng: "fr",
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export default i18n;
