# Guida alla migrazione da pc.yaml a Power Control

Questa guida descrive come passare dal vecchio package YAML (`pc.yaml`) alla nuova integrazione HACS.

---

## Metodo A — Migrazione automatica (consigliato)

La nuova integrazione rileva automaticamente la presenza del vecchio package e offre di importare la configurazione con un click.

### Prerequisiti

- Il vecchio package `pc.yaml` è ancora attivo (le entità `input_*` sono visibili in HA)
- La nuova integrazione è installata ma **non ancora configurata**

### Passi

1. **Installa** la nuova integrazione (HACS o manuale) senza rimuovere ancora il vecchio package

2. Vai in **Impostazioni → Integrazioni → Aggiungi integrazione** e cerca **Power Control**

3. Il wizard rileva le entità del vecchio package e mostra:

   > *"È stato rilevato il vecchio package PowerControl con N carichi configurati. Vuoi importare automaticamente la configurazione?"*

   Seleziona **Sì** e prosegui

4. Lo step successivo mostra un riepilogo della configurazione importata:
   - Numero di carichi e nomi
   - Soglia immediata e ritardata
   
   Se è tutto corretto, seleziona **Conferma**. Se vuoi modificare qualcosa, seleziona **No** per passare alla configurazione manuale con i campi pre-compilati

5. Scegli se **creare la dashboard** automaticamente, poi completa il wizard

6. Verifica che l'integrazione funzioni correttamente: controlla le entità create in **Impostazioni → Integrazioni → Power Control → Entità**

7. **Rimuovi il vecchio package**: elimina il file `pc.yaml` dalla directory dei packages di HA e rimuovi il riferimento in `configuration.yaml`. Riavvia HA

8. Rimuovi manualmente le entità `input_*` orfane se rimangono in **Impostazioni → Dispositivi e servizi → Entità**

---

## Metodo B — Migrazione manuale

Usa questo metodo se:
- Hai già rimosso il vecchio package prima di installare la nuova integrazione
- La migrazione automatica non ha rilevato correttamente la configurazione
- Preferisci configurare tutto da zero

### Valori da ricopiare

Prima di rimuovere il vecchio package, annota questi valori dalle entità HA:

| Entità vecchia | Campo nuovo | Dove trovarlo in HA |
|---|---|---|
| `input_number.potenza_massima_immediato` | Soglia distacco immediato (W) | Developer Tools → Stati |
| `input_number.potenza_massima_ritardato` | Soglia distacco ritardato (W) | Developer Tools → Stati |
| `input_number.tempo_stop_immediato` | Attesa prima del distacco immediato (s) | Developer Tools → Stati |
| `input_number.tempo_stop_ritardato` | Attesa prima del distacco ritardato (min) | Developer Tools → Stati |
| `input_number.attesa_stop` | Attesa tra un distacco e l'altro (s) | Developer Tools → Stati |
| `input_number.attesa_start` | Attesa tra una riattivazione e l'altra (min) | Developer Tools → Stati |
| `input_number.tempo_start` | Minuti sotto soglia prima di riattivare (min) | Developer Tools → Stati |
| `input_text.potenza_carichi` | Sensore potenza globale (entity_id) | Developer Tools → Stati |

Per ogni carico (da 1 a 20):

| Entità vecchia | Campo nuovo |
|---|---|
| `input_text.carico_N_potenza` | Sensore potenza del carico N |
| `input_text.carico_N_switch` | Interruttore del carico N |
| `input_boolean.mantini_spento_N` | Riattivazione automatica (**invertito**: `on` → disabilitata) |

### Passi

1. Annota i valori dalla tabella sopra

2. Rimuovi il file `pc.yaml` dalla directory dei packages e aggiorna `configuration.yaml`

3. Riavvia Home Assistant

4. Vai in **Impostazioni → Integrazioni → Aggiungi integrazione → Power Control**

5. Completa il wizard inserendo i valori annotati

---

## Mapping completo entità

### Impostazioni globali

| Vecchia entità | Nuovo campo | Note |
|---|---|---|
| `input_text.potenza_carichi` | Sensore potenza globale | Ignorato se puntava al sensore virtuale |
| `input_number.potenza_massima_immediato` | Soglia distacco immediato | In W |
| `input_number.potenza_massima_ritardato` | Soglia distacco ritardato | In W |
| `input_number.tempo_stop_immediato` | Delay distacco immediato | In secondi |
| `input_number.tempo_stop_ritardato` | Delay distacco ritardato | In minuti |
| `input_number.attesa_stop` | Attesa tra distacchi | In secondi |
| `input_number.attesa_start` | Attesa tra riattivazioni | In minuti |
| `input_number.tempo_start` | Attesa prima di riattivare | In minuti |
| `input_boolean.attiva_power_control` | Switch `power_control_attivo` | Entità nativa nella nuova integrazione |

### Per ogni carico

| Vecchia entità | Nuovo campo | Note |
|---|---|---|
| `input_text.carico_N_potenza` | Sensore potenza | entity_id |
| `input_text.carico_N_switch` | Interruttore | entity_id |
| `input_boolean.mantini_spento_N` | Riattivazione automatica | **Logica invertita**: `on` → `auto_restart = False` |

### Entità non migrate

Queste entità del vecchio package non hanno un equivalente diretto e vengono ignorate:

- `input_number.potenza_N_sospesa` — la potenza sospesa è ora gestita internamente dal coordinator e non richiede configurazione
- `input_boolean.sensore_trigger` — rimpiazzato dalla logica interna dei timer
- `input_boolean.selezione_script_python` — lo script Python non è più necessario
- `input_boolean.impostazioni_power_control` — rimpiazzato dall'options flow di HA

---

## Domande frequenti

**Le mie automazioni che usavano le vecchie entità `input_*` smettono di funzionare?**

Sì. Le entità `input_*` del vecchio package non esistono più nella nuova integrazione. Dovrai aggiornare le automazioni per usare:
- `switch.power_control_attivo` al posto di `input_boolean.attiva_power_control`
- I servizi `power_control.force_stop_load` / `power_control.force_start_load` al posto degli script `stop_carichi_generale` / `start_carichi_generale`
- I sensori `sensor.power_control_*` al posto degli `input_number.potenza_N_sospesa`

**Il sensore di potenza virtuale (`sensor.potenza_carichi_virtuale`) non c'è più?**

La potenza totale è ora disponibile come `sensor.power_control_potenza_attuale`. Il valore viene calcolato automaticamente come somma dei carichi se non è configurato un sensore globale.

**Posso tenere entrambi attivi temporaneamente?**

Sì, durante la transizione. Il vecchio package e la nuova integrazione non si interferiscono a patto che non abbiano gli stessi switch configurati. Una volta verificato che la nuova integrazione funziona correttamente, rimuovi il vecchio package.

**La priorità dei carichi è cambiata?**

No, la logica è identica: il carico 1 ha la massima priorità (viene spento per ultimo e riacceso per primo). L'unica differenza è che la numerazione inizia da 0 internamente nei servizi (`load_index: 0` corrisponde al carico 1).
