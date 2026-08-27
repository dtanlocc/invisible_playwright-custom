"""Il client Juggler in Python: lo stacco da Playwright, pezzo per pezzo.

| modulo | cosa fa |
|---|---|
| `protocol.py` | GENERATO da `scripts/gen_juggler_protocol.py` leggendo il `Protocol.js` che sta dentro il binario SPEDITO: 71 comandi, 34 eventi |
| `connection.py` | la pipe verso Juggler. JSON delimitato da un byte zero; fd 3/4 su POSIX, HANDLE ereditabili su Windows |
| `lifecycle.py` | albero dei frame, navigazioni, i quattro load state |
| `injected.py` | carica `injected.js` nel mondo di UTILITA' e lo chiama: selettori e actionability |
| `injected.js` | estratto dal bundle con `scripts/gen_injected_source.py`. Non e' upstream: porta le correzioni di stealth del fork |

⛔ **Nessun modulo del prodotto importa ancora questo pacchetto**: e' inerte per
costruzione, e lo resta finche' `_impl` non ci si appoggia. Cio' che manca sta
in `docs/firefox-stealth-architecture/32-stacco-da-playwright.md` §6, che e'
anche l'unico posto dove vivono il disegno e l'inventario dei vincoli.

⛔ **Cio' che vive qui ARRIVA all'utente**, perche' e' sotto
`src/invisible_playwright/`. Un attrezzo che serve solo a noi va in `scripts/`,
che nel wheel non entra.
"""
