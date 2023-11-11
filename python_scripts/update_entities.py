#group_entities = hass.states.get('group.all_lights').attributes['entity_id']
#all_lights = []
#for e in group_entities:
#    all_lights.append(e)
#service_data = {'entity_id': 'input_select.timer_generico7',
#                'options': all_lights}
#hass.services.call('input_select', 'set_options', service_data)


#group_entities = hass.states.get('group.all_lights').attributes['entity_id']
#all_lights = []
#for e in group_entities:
#    all_lights.append(hass.states.get(e).attributes['friendly_name'])
#service_data = {'entity_id': 'input_select.timer_generico7',
#                'options': all_lights}
#hass.services.call('input_select', 'set_options', service_data)


#entities = hass.states.entity_ids()
#service_data = {'entity_id': 'input_select.entities', 'options': sorted(entities)}
#hass.services.call('input_select', 'set_options', service_data)







entities = hass.states.entity_ids('switch')
all_switches = ["Seleziona"]
for e in entities:
    all_switches.append(e)

entities = hass.states.entity_ids('light')
for e in entities:
    all_switches.append(e)


service_data = {'entity_id': 'input_select.carico_1_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_2_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_3_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_4_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_5_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_6_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_7_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_8_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_9_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_10_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_11_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_12_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_13_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_14_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_15_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_16_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_17_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_18_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_19_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_20_switch', 'options': sorted(all_switches)}
hass.services.call('input_select', 'set_options', service_data)

entities = hass.states.entity_ids('sensor')
all_sensor = ["Seleziona"]
for e in entities:
    all_sensor.append(e)

service_data = {'entity_id': 'input_select.carico_1_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_2_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_3_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_4_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_5_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_6_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_7_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_8_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_9_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_10_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_11_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_12_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_13_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_14_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_15_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_16_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_17_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_18_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_19_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
service_data = {'entity_id': 'input_select.carico_20_potenza', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)

service_data = {'entity_id': 'input_select.potenza_carichi', 'options': sorted(all_sensor)}
hass.services.call('input_select', 'set_options', service_data)
