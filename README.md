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

# Configurazione
Impostare i parametri di configurazione dell'interfaccia grafica Lovelace.

# Sensore potenza carichi
La soluzione più efficace è utilizzare un sensore di potenza a monte dell'impianto, poco prima del contatore. In tal caso basta selezionare il sensore appropriato nella configurazione.
In alternativa è possibile utilizzare i sensori di potenza dei maggiori carichi utilizzati (sensor.potenza_carichi_virtuale) e mantenere un certo margine di tolleranza.
Questo comporta di monitorare tutti i maggiori carichi (forno, fornelli, phon, condizionatori, ecc...).
Naturalmente in questo modo non si può valutare il consumo complessivo, quindi si potrebbe superare il valore limite senza che intervenga il controllo carichi.
Ma utilizzando un valore conservativo di potenza massima (ad es. 3kW) e contando sulla tolleranze di 180 minuti fino al 33% (nell'es. 4kW) dovrebbe essere funzionale.

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
