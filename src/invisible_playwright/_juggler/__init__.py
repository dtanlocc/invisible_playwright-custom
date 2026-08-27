"""Il client Juggler in Python: il primo pezzo dello stacco da Playwright.

Oggi contiene solo `protocol.py`, GENERATO da `scripts/gen_juggler_protocol.py`
leggendo il `Protocol.js` che sta dentro il binario SPEDITO. Nessun altro modulo
lo importa ancora: e' inerte per costruzione, e lo resta finche' non arriva
`connection.py`.

Il disegno, l'inventario dei vincoli e l'ordine di lavoro stanno nel workbench,
in `docs/firefox-stealth-architecture/32-stacco-da-playwright.md`.

⛔ Cio' che vive qui ARRIVA all'utente: e' sotto `src/invisible_playwright/`.
Un attrezzo che serve solo a noi va in `scripts/`, che non entra nel wheel.
"""
