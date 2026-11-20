# 07 — WhatsApp messaging

## Provider interface

```python
class MessagingProvider(Protocol):
    def send_template(self, to: str, template: str, lang: str, params: list[str], buttons: list[str] | None = None) -> str: ...  # returns message id
    def send_text(self, to: str, text: str) -> str: ...          # only inside the 24 h customer-service window
    def send_media_link(self, to: str, url: str, caption: str) -> str: ...
```

Implementations: `WhatsAppCloudProvider` (Meta Graph API), `MockProvider` (stores messages in a `mock_messages` table and exposes them at `GET /dev/messages` + a simple web inbox in dev), `SmsFallbackProvider` (aggregator TBD, interface only in MVP).

Webhook: verify `X-Hub-Signature-256` with the app secret; respond 200 within 3 s; process asynchronously (Celery).

## Templates (to submit to Meta; category UTILITY)

`daily_report_fr`
```
Seetlu – {{1}} – {{2}}
Entrées : {{3}} · Servis : {{4}}
Argent enregistré : {{5}} F ({{6}})
{{7}}
Comptoir sans personne : {{8}} min · Heure la plus chargée : {{9}}
Par rapport à {{10}} dernier : {{11}}
Moments à voir : {{12}}
Répondez 1, 2 ou 3 pour voir un moment, « photo » pour une photo maintenant.
```
Params: 1 shop name, 2 date (e.g. « ven. 20 nov. »), 3 visitors_in, 4 served, 5 sales_xof formatted with thin spaces, 6 split by source (« Wave 45 000 · OM 12 000 · espèces 30 000 »), 7 verdict text (06), 8 unattended_min, 9 busiest hour (« 18h–19h »), 10 weekday name, 11 deltas (« entrées +12 %, argent −8 % ») or « pas de comparaison », 12 moment list (« 1) 14h02 comptoir vide 12 min 2) 19h40 attente 4 min ») or « aucun ».
If a value has low confidence append « (estimation) ».

`cash_prompt_fr`: « Seetlu – {{1}} : combien d'espèces dans la caisse ce soir ? Répondez avec le montant, ex : 85000. »

`alert_fr`: « Seetlu – {{1}} : {{2}} » with fixed texts per alert type:
- not_opened: « la boutique n'a pas encore ouvert ({{time}}). »
- unattended: « le comptoir est sans personne depuis {{min}} min. »
- after_hours_motion: « mouvement détecté après la fermeture à {{time}}. Répondez photo pour voir. »
- kit_offline: « le kit Seetlu ne répond plus depuis {{time}} (coupure de courant ou d'internet ?). »

`otp_fr` (AUTHENTICATION category): code template with copy button.

Wolof (`*_wo`) templates are v2; keep the template keys language-suffixed so adding them is config only.

## Inbound command grammar (case-insensitive, accents ignored, trimmed)

| Input | Who | Action |
| --- | --- | --- |
| `1` `2` `3` | owner, manager with clip access | Return clip link for that moment of the latest report (generate if needed; reply « vidéo en préparation » and send the link when ready) |
| `photo` | owner, manager with clip access | Snapshot command; send image when ready (timeout 2 min → « kit injoignable ») |
| `faux` | owner, manager | Ask « Combien d'entrées environ aujourd'hui ? » → number → `day_corrections` (metric visitors_in) |
| `+<amount>` | owner, manager, staff | Quick log sale; reply « ✓ {amount} F – total du jour : {total} F » |
| `<amount>` (reply to cash prompt within 3 h) | owner, manager | Cash declaration (replace) |
| `annuler` | sender of the last quick log (within 10 min) | Void their last quick log |
| `stop` / `start` | owner | Pause / resume reports |
| `aide` | anyone registered | Short help text |
| anything else | — | « Je n'ai pas compris. Tapez aide. » |
| unknown phone | — | No reply (log only) |

Amount parsing: strip spaces, dots, « F », « fcfa »; reject > 10 000 000 with « Montant trop élevé, vérifiez. »
