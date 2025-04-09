
[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]

![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Community Forum][forum-shield]][forum]

<a href="https://www.buymeacoffee.com/andthebad" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

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

## Installazione
- Copiare il file "packages/pc.yaml" nella directory "packages"
- Copiare i file "python_scripts/update_entities.py" e "python_scripts/update_entities_new.py" nella directory "python_scripts"
- In alternativa, è possibile scaricare il file ZIP ed estrarre il contenuto della cartella "HA_PowerControl-main" nella cartella di Home Assistant.
- [Abilitare i packages](https://www.home-assistant.io/docs/configuration/packages/)
- [Abilitare gli script python](https://www.home-assistant.io/integrations/python_script/)
- Aggiungere il contenuto del file "pc.lovelace" all'interfaccia Lovelace.
https://github.com/andbad/HA_PowerControl/assets/7837288/73233fa8-2143-4486-bd43-1dce41e59369
- Creare un gruppo di notifica "group.tutti" nel file "configuration.yaml" ed inserirvi i device che riceveranno le notifiche di intervento.
- [Configurare il recoder](https://www.home-assistant.io/integrations/recorder/) per includere i seguenti sensori:
  - sensor.potenza_carichi_selezionato
  - sensor.potenza_carichi_sospesa
  - sensor.potenza_massima_immediato
  - sensor.potenza_massima_ritardato

## Configurazione
Impostare i parametri di configurazione dell'interfaccia grafica Lovelace.
ATTENZIONE: cliccare su "Esegui" accanto a "Salva configurazione" per salvare i parametri impostati, altrimenti andranno persi al successivo riavvio.

## Sensore potenza carichi
La soluzione più efficace è utilizzare un sensore di potenza a monte dell'impianto, poco prima del contatore. In tal caso basta selezionare il sensore appropriato nella configurazione.
In alternativa è possibile utilizzare i sensori di potenza dei maggiori carichi utilizzati (sensor.potenza_carichi_virtuale) e mantenere un certo margine di tolleranza.
Questo comporta di monitorare tutti i maggiori carichi (forno, fornelli, phon, condizionatori, ecc...).
Naturalmente in questo modo non si può valutare il consumo complessivo, quindi si potrebbe superare il valore limite senza che intervenga il controllo carichi.
Ma utilizzando un valore conservativo di potenza massima (ad es. 3kW) e contando sulla tolleranze di 180 minuti fino al 33% (nell'es. 4kW) dovrebbe essere funzionale.

## Disinstallazione package
Per eliminare il package basta eliminare i file che lo compongono:
  - ./python_scripts/update_entities.py
  - ./python_scripts/update_entities_new.py
  - ./packages/pc.yaml

Eliminare la pagina nell'interfaccia (click sull'icona della matita, poi "Elimina vista").\
Eliminare il gruppo di notifica "group.tutti"\
Eliminare dal [recoder](https://www.home-assistant.io/integrations/recorder/) i seguenti sensori:
  - sensor.potenza_carichi_selezionato
  - sensor.potenza_carichi_sospesa
  - sensor.potenza_massima



## Screenshot
![pc_new](https://github.com/andbad/HA_PowerControl/assets/7837288/329312df-9b3c-4e11-8a57-0a11712186a2)
![1](https://user-images.githubusercontent.com/7837288/212674703-2ba39593-9dea-4e0d-8f14-76562bd82f96.png)

## Debug
E' possibile attivare la scrittura di messaggi di log abilitando il componente relativo nella [sezione logger](https://www.home-assistant.io/integrations/logger/) del file di configurazione configuration.yaml:
```python
logger:
  default: error
  logs:
    homeassistant.components.pc: debug
```

[buymecoffee]: https://www.buymeacoffee.com/andthebad
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/andbad/homeassistant-carwings.svg?style=for-the-badge
[commits]: https://github.com/andbad/HA_PowerControl/commits/main
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://github.com/indomus/forum
[license-shield]: https://img.shields.io/github/license/andbad/homeassistant-carwings.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-andbad-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/andbad/homeassistant-carwings.svg?style=for-the-badge
[releases]: https://github.com/andbad/HA_PowerControl/releases
[hacs-repo-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
