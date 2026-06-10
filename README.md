# HA Power Control

<p align="center">
  <img src="logo.png" alt="HA Power Control Logo" width="200"/>
</p>

<a href="https://www.buymeacoffee.com/andthebad" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
![GitHub Release](https://img.shields.io/github/v/release/andbad/HA_PowerControl)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/andbad/HA_PowerControl)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integrazione per Home Assistant che previene il distacco del contatore gestendo automaticamente i carichi elettrici in base alla potenza assorbita.

---

## Come funziona

Quando il consumo totale supera una soglia configurata, l'integrazione spegne i carichi **in ordine di priorità inversa** (dal meno importante al più importante), uno alla volta, fino a rientrare nel limite.

Quando il consumo torna sotto soglia per un tempo sufficiente, i carichi vengono **riattivati automaticamente** in ordine di priorità diretta, verificando che ogni riattivazione non causi un nuovo sforamento.

### Due modalità di distacco

| Modalità | Soglia | Ritardo |
|---|---|---|
| **Immediato** | Soglia immediata (es. 3300 W) | Configurabile in secondi |
| **Ritardato** | Soglia ritardata (es. 3000 W) | Configurabile in minuti |

---

## Requisiti

- Home Assistant 2023.6 o superiore
- Dispositivi con switch controllabile (es. Shelly 1PM, Shelly Plug S)
- Sensori di potenza per i carichi da gestire (W)
- Opzionale: sensore di potenza globale dell'impianto (es. Shelly EM)

---

## Installazione via HACS

1. In HACS, vai su **Integrazioni → ⋮ → Repository personalizzati**
2. Aggiungi `https://github.com/andbad/HA_PowerControl` come tipo **Integrazione**
3. Cerca "Power Control" e installa
4. Riavvia Home Assistant

### Installazione manuale

Copia la cartella `custom_components/power_control/` nella directory `custom_components/` della tua installazione HA, poi riavvia.

---

## Configurazione

1. Vai in **Impostazioni → Integrazioni → Aggiungi integrazione**
2. Cerca **Power Control**
3. Segui il wizard in tre passi:

### Passo 1 — Impostazioni globali

| Campo | Descrizione | Default |
|---|---|---|
| Nome istanza | Nome visualizzato in HA | Power Control |
| Sensore potenza globale | entity_id del sensore totale (opzionale) | — |
| Soglia immediata | W oltre cui il distacco è immediato | 3000 W |
| Soglia ritardata | W oltre cui il distacco avviene dopo N minuti | 2700 W |
| Delay distacco immediato | Secondi di permanenza sopra soglia | 30 s |
| Delay distacco ritardato | Minuti di permanenza sopra soglia | 10 min |
| Attesa tra distacchi | Secondi tra lo spegnimento di un carico e il successivo | 10 s |
| Attesa tra riattivazioni | Minuti tra la riattivazione di un carico e il successivo | 5 min |
| Attesa prima di riattivare | Minuti sotto soglia prima di iniziare le riattivazioni | 5 min |
| Servizio notifica | es. `notify.mobile_app_telefono` (opzionale) | — |

> **Nota:** la soglia immediata deve essere maggiore della soglia ritardata.

### Passo 2 — Numero di carichi

Scegli quanti carichi gestire (1–20). I carichi sono ordinati per priorità: **il carico 1 è il più importante** e sarà l'ultimo ad essere spento.

### Passo 3 — Configurazione carichi (ripetuto per ogni carico)

| Campo | Descrizione |
|---|---|
| Nome | Etichetta visualizzata nelle notifiche e in HA |
| Sensore potenza | entity_id del sensore (es. `sensor.potenza_lavatrice`) |
| Interruttore | entity_id dello switch (es. `switch.shelly_lavatrice`) |
| Riattivazione automatica | Se disabilitato, il carico non viene mai riacceso automaticamente |

---

## Entità create

Tutte le entità sono raggruppate sotto un unico dispositivo **Power Control**.

### Sensori

| Entità | Descrizione |
|---|---|
| `sensor.power_control_potenza_attuale` | Potenza misurata in tempo reale (W) |
| `sensor.power_control_potenza_sospesa` | Somma delle potenze dei carichi sospesi (W) |
| `sensor.power_control_soglia_distacco_immediato` | Soglia immediata configurata (W) |
| `sensor.power_control_soglia_distacco_ritardato` | Soglia ritardata configurata (W) |
| `sensor.power_control_<nome>_potenza_sospesa` | Potenza sospesa per ogni singolo carico (W) |

I sensori per carico espongono anche questi attributi:

- `current_power_w` — potenza istantanea misurata
- `switch_state` — stato dello switch (`on` / `off` / `unavailable`)
- `auto_restart` — riattivazione automatica abilitata
- `keep_off` — carico bloccato manualmente
- `is_suspended` — carico attualmente sospeso

### Switch

| Entità | Descrizione |
|---|---|
| `switch.power_control_attivo` | Abilita/disabilita l'intero sistema. Lo stato sopravvive al riavvio di HA. |

---

## Servizi

| Servizio | Parametri | Descrizione |
|---|---|---|
| `power_control.enable` | — | Abilita il controllo carichi |
| `power_control.disable` | — | Disabilita e resetta tutte le potenze sospese |
| `power_control.reset_load` | `load_index` (0–19) | Rimuove un carico dalla lista sospesi |
| `power_control.force_stop_load` | `load_index` (0–19) | Distacco immediato di un carico specifico |
| `power_control.force_start_load` | `load_index` (0–19) | Riattivazione immediata, ignora i timer |

L'`load_index` corrisponde alla posizione del carico nel wizard (0 = prima posizione = massima priorità). Lo trovi anche come attributo `load_index` sul sensore del carico.

---

## Dashboard

La dashboard Lovelace viene creata automaticamente al termine del wizard di configurazione, se si abilita l'opzione **"Crea dashboard"**. Non è necessario importare nessun file manualmente.

La dashboard include:

- Gauge del carico impianto con colori (verde/giallo/rosso)
- Stato in tempo reale di potenza attuale e sospesa
- Grafico storico dell'ultima ora
- Card di configurazione con soglie e parametri di timing
- Card timer con progress bar per i timer interni
- Card per ogni carico configurato con sensore di potenza e stato sospensione

La dashboard è disponibile nella barra laterale come **Power Control** e viene rimossa automaticamente quando si elimina l'integrazione.

---

## Sensore di potenza globale vs virtuale

**Con sensore globale** (consigliato): configura l'entity_id di un sensore che misura tutta la potenza assorbita dall'impianto (es. Shelly EM). Il sistema usa quel valore direttamente.

**Senza sensore globale**: il sistema somma le potenze dei singoli carichi configurati. Funziona, ma non vede i consumi dei carichi non monitorati — usa soglie conservative.

---

## Comportamento al riavvio di HA

- Lo stato del master switch (`attivo` / `disattivo`) viene ripristinato
- Le potenze sospese vengono ripristinate leggendo l'ultimo stato delle entità sensore
- Se un carico era sospeso prima del riavvio, rimane nella lista di attesa per la riattivazione

---

## Crediti

Basato sul package YAML originale [HA_PowerControl](https://github.com/andbad/HA_PowerControl) di **andbad**, sviluppato con il supporto della community [InDomus](https://indomus.it/).
