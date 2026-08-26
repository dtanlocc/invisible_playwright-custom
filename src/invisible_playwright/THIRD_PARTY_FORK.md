# Fork di Playwright incluso in questo pacchetto

Questo pacchetto include e ridistribuisce una copia MODIFICATA di
[Playwright](https://github.com/microsoft/playwright), di Microsoft Corporation,
sotto licenza **Apache-2.0**. Il codice di `invisible_playwright` che non sta
nelle due cartelle qui sotto resta **MIT**; il `pyproject.toml` lo dichiara come
`license = "MIT AND Apache-2.0"`, perche' dire solo MIT direbbe il falso su cosa
l'utente riceve.

## Cosa e' vendorizzato

| cartella | cos'e' | licenza |
|---|---|---|
| `_pw/` | il client Python di Playwright, versione **1.61.1** | Apache-2.0 (`_pw/LICENSE`) |
| `_driver/` | il driver Node di Playwright | Apache-2.0 (`_driver/package/LICENSE`, `NOTICE`, `ThirdPartyNotices.txt` - a monte, non toccati) |

Il namespace del client e' `invisible_playwright._pw` invece di `playwright`, per
non collidere con un eventuale `playwright` di serie installato accanto.

## Le modifiche rispetto al Playwright originale

Sono nel bundle del driver (`_driver/package/lib/coreBundle.js`), non nel client:

- **[B177]** corretto `set_content`, che nel driver di serie non attendeva il
  caricamento nel modo che serve a una pagina pilotata in modo indistinguibile.
- **Rimossi ~643 KB** di sottosistemi che non usiamo e che allargano soltanto la
  superficie: supporto android ed electron, il protocollo bidi, il recorder, e i
  motori chromium e webkit (questo pacchetto pilota solo un Firefox).
- **Neutralizzato `_exposeConsoleApi`**: il driver di serie esponeva una API di
  console che una pagina poteva osservare.
- **Tolta `console.debug`** dal codice iniettato, per la stessa ragione.

## Perche' e' in git

Senza queste due cartelle il pacchetto **si installa ma non si importa**: il
`launcher.py` importa da `invisible_playwright._pw`, e un wheel costruito da un
checkout che non le contiene alza `ImportError` a ogni `import
invisible_playwright`. Lasciarle fuori da git era un pacchetto rotto che solo
l'utente vedeva. La storia completa della decisione sta nel workbench, in
`docs/firefox-stealth-architecture/72-next-steps.md`, voce 23.
