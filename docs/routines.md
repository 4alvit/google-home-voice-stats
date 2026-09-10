# Google Routines → HA stats

Google Assistant often cannot answer arbitrary sensor questions natively. Pattern:

1. Create an HA **script** that speaks the value (Nest broadcast / `tts.google_translate_say` / your notify path).
2. In Google Home, create a **Routine** with the phrase you want (“solar status”).
3. Routine action: call the HA script (via exposed script, webhook with auth, or Nabu Casa cloud hook — pick what you already use).
4. Keep the webhook authenticated; rotate secrets; never commit them here.
