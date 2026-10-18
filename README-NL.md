# PanoStack (v9.8 - ART Editie)

**PanoStack** is een geautomatiseerd hulpprogramma voor een hoogwaardige RAW-workflow, speciaal ontworpen voor fotografen. Het stroomlijnt het sorteren, het samenvoegen van belichtingstrapjes (HDR en ruisonderdrukking via Burst-stacking) en het naadloos stitchen van panorama's in één overzichtelijke pijplijn.

---

## Belangrijkste functionaliteiten & Architectuur

### 1. RAW-conversie via ART-cli
Het hart van de verwerking binnen PanoStack is **ART-cli** (*Another RawTherapee* command-line interface):
* **16-bit TIFF-ontwikkeling:** Alle RAW-bestanden (`.rw2`, `.arw`, `.cr2`, `.cr3`, `.nef`, `.orf`, `.raf`, `.dng`) worden via ART-cli gedemosaiced en omgezet naar 16-bit TIFF-bestanden met behoud van het volledige dynamische bereik, nog vóórdat het uitlijnen of stitchen begint.
* **Vrije profielkeuze (`.arp`):** Maak gebruik van het standaard ingebouwde profiel of selecteer een eigen aangepast `.arp`-profiel (*Vrije ARP*). Hiermee worden automatische lenscorrecties (vertekening, vignettering en chromatische aberratie), tooncurven en kleurprofielen uniform op alle deelopnamen toegepast.

### 2. Flexibele nabewerking ("Start Fotoprogramma")
Nadat een panorama is samengesteld of tussenresultaten zijn gegenereerd, kunnen deze direct worden geopend in een nabewerkingsprogramma naar keuze:
* **Vrije programmakeuze:** Kies via het invoerveld eenvoudig tussen standaardopties zoals `art`, `darktable`, `ansel` of `gimp`, of typ zelf de naam van een geïnstalleerd programma in.
* **Zelfstandige start:** Externe programma's starten losgekoppeld (detached) op de achtergrond. Hierdoor bevriest PanoStack niet en kan zowel het voltooide panorama als elk geselecteerd DNG/TIFF/RAW-bestand direct worden geopend.

---

## Overzicht van de Tabbladen

### Tab 1: Sorteren ("1. Sorteren")
Scant bronmappen en structureert foto's chronologisch op basis van EXIF-metadata in mappen per cameramodel en datum:
* **HDR Gap:** Maximale tussentijd (in seconden) tussen opnamen met verschillende sluitertijden (belichtingstrapjes).
* **Burst / Pano Gap:** Maximale tussentijd (standaard: 3.0s) tussen opnamen met identieke belichtingsinstellingen (panorama-series of snelle burst-opnamen).
* **Kopie 1e van reeks:** Plaatst automatisch een kopie van het eerste beeld in de hoofdmap voor een vlot overzicht.

### Tab 2: HDR Stacking ("2. HDR")
Voegt belichtingstrapjes samen tot beelden met een hoog dynamisch bereik:
* **Enfuse (16-bit TIFF):** RAW-bestanden worden via **ART-cli** ontwikkeld met het gekozen `.arp`-profiel, op sub-pixelniveau uitgelijnd met `align_image_stack` en samengevoegd met `enfuse`.
* **HDRmerge (32-bit Floating-Point DNG):** Voegt de onbewerkte sensordata direct samen tot een 32-bit lineair DNG-bestand voor maximale speelruimte in hooglichten en schaduwen.
* **Dubbele voortgangsbalk:** Geeft inzicht in zowel de totale voortgang als de voortgang per individueel frame.

### Tab 3: Burst Stacking ("3. Burst")
Onderdrukt ruis bij opnamen uit de hand met een hoge ISO-waarde:
* Ontwikkelt frames via **ART-cli**, lijnt het perspectief uit en past een mediaanberekening toe via ImageMagick voor een schoon, ruisvrij 16-bit resultaat zonder bewegingsonscherpte.

### Tab 4: Panorama Stitchen & Beheer ("4. Panorama")
* **Omschakelen tussen weergaven:** Schakel direct tussen tussenresultaten (*TIFF/JPG*, *DNG*), series (*RAW Serie*) of enkele referentieframes (*RAW enkel*). De verzamelmap navigeert automatisch mee naar de bijbehorende `TIFF/`- of `DNG/`-submap.
* **Betrouwbare previews:** Meertraps preview-lader die probleemloos omgaat met ingesloten EXIF-JPEG's, snelle `ART-cli -s` previews voor HDRmerge-DNG's, en automatische terugval via ImageMagick voor grote 16-bit TIFF's.
* **Twee Stitching Engines:**
  * **16-bit Hugin CLI:** Professionele geautomatiseerde pijplijn (`pto_gen`, `cpfind`, `cpclean`, `autooptimiser`, `pano_modify` en `hugin_executor`) inclusief automatische nivellering en overvloeiing. Bevat een optionele *"Open GUI"*-modus.
  * **Ultra-HQ OpenCV (8-bit):** Snelle engine voor previews en projecties via een 16-naar-8-bit compressiepijplijn (Percentile Stretching + Lab-CLAHE).

---

## Systeemvereisten (Linux)

Installeer de benodigde pakketten via uw pakketbeheerder:

```bash
# Arch Linux / Manjaro
sudo pacman -S art hugin enblend-enfuse perl-image-exiftool imagemagick pyside6 python-opencv python-numpy python-psutil

# AUR (Vereist voor DNG-samenvoeging)
yay -S hdrmerge
