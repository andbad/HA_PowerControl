# HA_PowerControl
Il package seguente, unito allo script python "update_entities.py" mira ad evitare il distacco del contatore a causa della troppa potenza assorbita dai vari elettrodomestici (carichi).
Requisito hardware fondamentale è la presenza di switch sui carichi da controllare e di un sensore che misura la potenza dei singoli carichi. 
Ho utilizzato dispositivi Shelly 1PM e Shelly Plug S, perfetti per lo scopo.
E' consigliato, ma non tassativo, l'utilizzo di un sensore che monitori il consumo complessivo dell'impianto (es. Shelly EM o un ESP8266+PZEM).
La logica prevede la configurazione di due soglie di potenza massima e due tempistiche di intervento (che rispecchiano la logica di funzionamento dei contatori di energia elettrica utilizzati in Italia):
- se l'assorbimento complessivo supera il valore di "Potenza Massima Ritardato", il pacchetto attende il valore in minuti di "Minuti distacco ritardato", dopo i quali inizia a scollegare i carichi;
- se l'assorbimento complessivo supera invece il valor di "Potenza massima immediato", attende un numero di secondi impostato in "Secondi distacco immediato" e poi inizia il distacco.

Lo scollegamento dei carichi che stanno assorbendo energia parte da quelli a minore priorità (Carico 20) fino a quelli a maggiore priorità (Carico 1), fino a che l'utilizzo complessivo della potenza rientri nel limite prefissato. Se un carico non sta assorbendo, non viene distaccato.
Lo script tiene memoria dell'assorbimento del carico prima del distacco e lo ricollega solo quando la disponibilità di potenza è sufficiente a non causare un nuovo distacco, in ordine di priorità inverso (da Carico 1 a Carico 20).
La configurazione è interamente tramite interfaccia grafica, tranne il gruppo di notifica (notify.tutti) che va impostato manualmente.

# Installazione
- Copiare il file "packages/pc.yaml" nella directory "packages"
- Copiare i file "python_scripts/update_entities.py" e "python_scripts/update_entities_new.py" nella directory "python_scripts"
- In alternativa, è possibile scaricare il file ZIP ed estrarre il contenuto della cartella "HA_PowerControl-main" nella cartella di Home Assistant.
- [Abilitare i packages](https://www.home-assistant.io/docs/configuration/packages/)
- [Abilitare gli script python](https://www.home-assistant.io/integrations/python_script/)
- Aggiungere il contenuto del file "pc.lovelace" all'interfaccia Lovelace.
- Creare un gruppo di notifica "notify.tutti" nel file "configuration.yaml" ed inserirvi i device che riceveranno le notifiche di intervento.
- [Configurare il recoder](https://www.home-assistant.io/integrations/recorder/) per includere i seguenti sensori:
  - sensor.potenza_carichi_selezionato
  - sensor.potenza_carichi_sospesa
  - sensor.potenza_massima

# Configurazione
Impostare i parametri di configurazione dell'interfaccia grafica Lovelace.
ATTENZIONE: cliccare su "Esegui" accanto a "Salva configurazione" per salvare i parametri impostati, altrimenti andranno persi al successivo riavvio.

# Sensore potenza carichi
La soluzione più efficace è utilizzare un sensore di potenza a monte dell'impianto, poco prima del contatore. In tal caso basta selezionare il sensore appropriato nella configurazione.
In alternativa è possibile utilizzare i sensori di potenza dei maggiori carichi utilizzati (sensor.potenza_carichi_virtuale) e mantenere un certo margine di tolleranza.
Questo comporta di monitorare tutti i maggiori carichi (forno, fornelli, phon, condizionatori, ecc...).
Naturalmente in questo modo non si può valutare il consumo complessivo, quindi si potrebbe superare il valore limite senza che intervenga il controllo carichi.
Ma utilizzando un valore conservativo di potenza massima (ad es. 3kW) e contando sulla tolleranze di 180 minuti fino al 33% (nell'es. 4kW) dovrebbe essere funzionale.

# Screenshot
![pc_new](https://github.com/andbad/HA_PowerControl/assets/7837288/329312df-9b3c-4e11-8a57-0a11712186a2)
![1](https://user-images.githubusercontent.com/7837288/212674703-2ba39593-9dea-4e0d-8f14-76562bd82f96.png)

# Debug
E' possibile attivare la scrittura di messaggi di log abilitando il componente relativo nella [sezione logger](https://www.home-assistant.io/integrations/logger/) del file di configurazione configuration.yaml:
```python
logger:
  default: error
  logs:
    homeassistant.components.pc: debug
```
