# SALUS Gulvkomfort – én automation, uafhængige rum

Vejrudsigten starter komforten. Efter minimumløbetiden vurderes udetemperaturen
nu. Hvert rum får egne perioder og sin egen pause, selv om du bruger **én fælles
automation**. Rumminimum kan kun fastholde sit eget aktive rum. Den øvre
rumgrænse kan afbryde straks.

Dette er en selvstændig prøveudgave. Den er testet med Home Assistants rigtige
blueprint- og handlingsmotor med simulerede enheder. Den nye udskilte udgave er
endnu ikke afprøvet på fysiske termostater. Din eksisterende beta ændres ikke.

## Tydeligere formular i HA 2026.11

[Den nye formular](https://github.com/MichaelBusackBertelsen/salus-comfort-blueprint/blob/main/blueprints/automation/salus_floor_comfort_da_conditional.yaml)
beholder de to kontakter. Minimumtemperatur og buffer vises kun, når minimum er
slået til. Øvre temperatur vises kun, når straks-afbrydelse er slået til.
Kræver **HA 2026.11.0+**. Den gamle formular er fortsat tilgængelig til ældre HA.

Importér den nye fil, og ret kun `use_blueprint.path` i den eksisterende
automations YAML til den importerede filsti. Behold automationens `id`, navn,
rum, hjælpere og alle `input`-værdier. Den samme automation beholder dermed sin
identitet og de eksisterende rumhjælpere. Kør ikke en ekstra regel på samme rum.
En temperatur, som er skjult, bruges ikke, mens kontakten er slået fra.

**Bruger du SALUS b15 uden Timer-/Tekst-hjælpere?** Brug i stedet
[b15-formularen og vejledningen](https://github.com/MichaelBusackBertelsen/homeassistant_salus/blob/feature/floor-dashboard/BLUEPRINT-2026-11.md).
Den bruger din eksisterende controller; ingen nye hjælpere er nødvendige.

## Opret hjælperne

Gå til **Indstillinger → Enheder og tjenester → Hjælpere → Opret hjælper**.
For **hvert rum** opretter du:

1. En **Timer** til komfortperioden. Slå **Gendan** til.
2. En **Timer** til pausen. Slå **Gendan** til.
3. En **Tekst** til rummets status. Sæt **maksimumlængde til 255**. Lad værdien
   være tom. Hvis du bruger YAML, skal den ikke have en `initial`-værdi.

Giv dem navne med rummet, så de er lette at vælge. Hjælperne må ikke deles mellem
rum eller automationer. Du skal stadig kun oprette én automation.

## Importér og konfigurér

Kræver Home Assistant 2026.2 eller nyere, timeprognoser og Gulvkomfort-selects med
de underliggende værdier `off`, `level_1`, `level_2` og `level_3`. Ventende,
optimistiske værdier skal markeres med Home Assistants standard `assumed_state`.

1. Åbn **Indstillinger → Automatiseringer og scener → Blueprints**.
2. Vælg **Importér blueprint**, og indsæt [linket til den danske blueprint](https://github.com/MichaelBusackBertelsen/salus-comfort-blueprint/blob/main/blueprints/automation/salus_floor_comfort_da.yaml).
3. Opret én automation fra den. Under **Rum** tilføjer du alle rum og vælger
   Gulvkomfort, termostat og rummets tre hjælpere.
4. Vælg vejrudsigt og eventuelt udeføler øverst. Gennemgå tændgrænse,
   minimumløbetid, forlængelse, slukgrænse, rumgrænser og pause. Gem.

Formularen forklarer hvert felt. Alle grænser er i °C. Vejrudsigten bruges altid
ved start. Udeføleren bruges ved stop; mangler den en gyldig måling, bruges
vejrtjenestens temperatur **nu**, aldrig en fremtidig prognosetime.

Eksempel: Under 8 °C i mindst én prognosetime inden for de næste otte timer
starter et ledigt rum nu. Ved seks timers minimumløbetid vurderes stop først
efter seks timer fra bekræftet start. Er det stadig under slukgrænsen, får rummet
fx en time mere. Prognosen genfortolkes ikke for at afbryde den aktive periode.
Det er lufttemperatur, ikke beregnet “føles som”.

## Se status, og slå reglen fra

På Gulvkomfort-entitetens **Aktivitet** ses prognosen bag tændingen, bekræftelse,
forlængelser og årsager, stop og pause. Gemmetiden følger din Recorder-opsætning.
Tekst-hjælperen gemmer seneste status, ikke hele historikken. Automationen gemmer
30 sporinger. Aktivitetsbeskeder er foreløbig på engelsk.

På [SALUS Climate Card](https://github.com/MichaelBusackBertelsen/salus-room-card)
vælger du rummets Tekst-hjælper i `comfort_state` og den fælles automation i
`comfort_automation`. Oplysningerne vises kun, når kortet er foldet ud.

Du slår **automationen** fra på automationslisten. Det slukker ikke automatisk
komforten; timerne fortsætter. Skal den stoppe nu, slår du automationen fra og
sætter Gulvkomfort til Fra manuelt. Ved genaktivering afstemmes status ved næste
planlagte kontrol, senest efter 15 minutter, eller ved en relevant hændelse.

En start uden bekræftelse inden 150 sekunder går i pause. Et ubekræftet stop
giver en ny vurdering efter fem minutter; hvis behovet stadig er der, kan den
sende en ny stopanmodning. Den gensender ikke straks. Manglende vejrdata kan
ikke starte nye rum; et aktivt rum forlænges, hvis stopgrundlaget mangler.

## Flyt fra den gamle beta

Opret den nye automation **deaktiveret**, og overfør dine grænser og rum.
Deaktivér den gamle vejrregel, før du aktiverer den nye. To regler må ikke
styre de samme rum samtidig. Gamle perioder overføres ikke automatisk.
Vælg, om nye regler må overtage manuelt aktiv komfort; alternativt bekræft
Gulvkomfort som Fra på rummene først. Nye starter og overtagelser får en ny
minimumperiode. Behold den gamle regel deaktiveret, indtil du har afprøvet den nye.

Kort installeres separat gennem **HACS → Dashboard**. Blueprint importeres her
gennem **Blueprints**. Ingen af delene installerer eller ændrer din gateway.

[Fuld teknisk beskrivelse og fejlhåndtering](README.md) ·
[Eksempel på YAML-hjælpere](examples/helpers.yaml)
