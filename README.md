# HA_PowerControl
Il package seguente, unito allo script python "update_entities.py" mira ad evitare il distacco del contatore a causa della troppa potenza assorbita dai vari elettrodomestici (carichi).
Requisito hardware fondamentale è la presenza di switch sui carichi da controllare e di un sensore che misura la potenza dei singoli carichi. 
Personalmente ho utilizzato dispositivi Shelly 1PM e Shelly Plug S, perfetti per lo scopo.
E' consigliato, ma non tassativo, l'utilizzo di un sensore che monitori il consumo complessivo dell'impianto (es. Shelly EM).
La logica prevede che in caso l'utilizzo complessivo superi il valore limite impostato, il pacchetto inizi il distacco dei carichi a minore priorità (Carico 10) fino a quelli a maggiore priorità (Carico 1),fino a che l'utilizzo complessivo della potenza rientri nel limite prefissato. 

Lo script tiene memoria dell'assorbimento del carico prima del distacco e lo ricollega solo quando la disponibilità di potenza è sufficiente a non causare un nuovo distacco, in ordine di priorità inverso (da Carico 1 a Carico 10).
La configurazione è interamente tramite interfaccia lovelace, tranne il gruppo di notifica (notify.tutti) che va impostato manualmente.

# Installazione
- Copiare il file "pc.yaml" nella directory "packages"
- Copiare il file "update_entities.py" nella directory "python_scripts"
- Abilitare i packages: https://www.home-assistant.io/docs/configuration/packages/
- Abilitare gli script python: https://www.home-assistant.io/integrations/python_script/
- Aggiungere il contenuto del file "pc.lovelace" all'interfaccia Lovelace.
- Creare un gruppo di notifica "notify.tutti" nel file "configuration.yaml" ed inserirvi i device che riceveranno le notifiche di intervento.
- Configurare il logger per includere i seguenti sensori:
  - sensor.potenza_carichi_selezionato
  - sensor.potenza_carichi_phantom
  - sensor.potenza_massima

# Configurazione
Impostare i parametri di configurazione dell'interfaccia grafica Lovelace.

# Sensore potenza carichi
La soluzione più efficace è utilizzare un sensore di potenza a monte dell'impianto, poco prima del contatore. In tal caso basta selezionare il sensore appropriato nella configurazione.
In alternativa è possibile utilizzare i sensori di potenza dei maggiori carichi utilizzati (sensor.potenza_carichi_virtuale) e mantenere un certo margine di tolleranza.
Questo comporta di monitorare tutti i maggiori carichi (forno, fornelli, phon, condizionatori, ecc...).
Naturalmente in questo modo non si può valutare il consumo complessivo, quindi si potrebbe superare il valore limite senza che intervenga il controllo carichi.
Ma utilizzando un valore conservativo di potenza massima (ad es. 3kW) e contando sulla tolleranze di 180 minuti fino al 33% (nell'es. 4kW) dovrebbe essere funzionale.

# Soglie di distacco
Vi sono due limiti massimi: nel caso in cui si superi il valore massimo "ritardato", il sitema attenderà alcuni minuti (regolabili da apposita opzione) prima di procedere con il distacco; nel caso in cui si superi il valore massimo immediato, il distacco avviene invece dopo alcuni secondi (anche in questo caso regolati da relativo slider).

I due limiti sono pensati per replicare il comportamento del contatore di energia elettronico standard di ENEL Distribuzione, che permette di assorbire fino al 10% in più del massimo contrattuale a tempo indefinitio e fino al 33% in più per un massimo di 3 ore. Superata questa soglia, il distacco del contatore avviene entro 2 minuti.
Ad esempio, per un contratto standard da 3000W (3kW), si può impostare un valore di potenza massima ritardato di 3200W (il massimo consentito da ENEL senza limiti sarebbe di 3300), con un tempo di distacco dopo 170 minuti (contro un massimo del contatore di 180). Per il valore di potenza massima istantaneo invece, si può impostare un valore di 3900W (contro i 4000W massimi teorici del contatore) ed un tempo di intervento di 10 secondi (per dare il tempo al package di distaccare i carichi necessari a rientrare sotto soglia).
Nell'interfaccia di configurazione sono indicati nella guida questi valori di riferimento. Ovviamente in caso la disponibilità al contatore sia superiore ai canonici 3kW andranno calcolati di conseguenza per le percentuali sopra indicate.

# Screenshot
![image](https://user-images.githubusercontent.com/7837288/107847400-773a8c80-6deb-11eb-9c08-90e9998ffe08.png)

![image](https://user-images.githubusercontent.com/7837288/107847409-8f121080-6deb-11eb-928e-3115360aa561.png)

# Debug
E' possibile attivare la scrittura di messaggi di log abilitando il componente relativo nella sezione logger del file di configurazione configuration.yaml:
```python
logger:
  default: error
  logs:
    homeassistant.components.pc: debug
```

# Credits
Il pacchetto, seppur scritto da 0, ha tratto ispirazione da: https://hassiohelp.eu/2020/10/14/nuovo-controllo-carichi/ 
