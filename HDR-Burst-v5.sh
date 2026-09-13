#!/bin/bash

# Forceer opening in een Konsole-venster dat niet direct sluit bij een fout
if [ ! -t 1 ]; then
    exec konsole --noclose -e bash "$0" "$@"
fi

echo "Script gestart..."

if ! command -v kdialog &> /dev/null; then
    echo "Fout: kdialog is niet geïnstalleerd."
    exit 1
fi

# ==========================================
# STAP 1: GRAFISCHE MAP-KEUZE
# ==========================================
target_dir=$(kdialog --getexistingdirectory "$HOME" --title "Stap 1/3: Selecteer de map met .RW2 bestanden")

if [ -z "$target_dir" ]; then
    echo "Geen map geselecteerd of geannuleerd."
    exit 0
fi

cd "$target_dir" || { echo "Fout: Kan niet naar map navigeren: $target_dir"; exit 1; }

# ==========================================
# STAP 2: GRAFISCHE BITDIEPTE-KEUZE
# ==========================================
BIT_DEPTH=$(kdialog --combobox "Stap 2/3: Kies de gewenste bitdiepte voor de TIFF-bestanden:" "16" "8" --default "16" --title "Bitdiepte keuze")

if [ -z "$BIT_DEPTH" ]; then
    echo "Geen bitdiepte gekozen of geannuleerd."
    exit 0
fi

# ==========================================
# STAP 3: OPTIONEEL XMP-PROFIEL SELECTEREN
# ==========================================
xmp_file=$(kdialog --getopenfilename "$HOME" "*.xmp" --title "Stap 3/3: Selecteer een Darktable .xmp bestand (of annuleer voor standaard)")

TIME_THRESHOLD=6.0
MAX_BURST_SIZE=8

mkdir -p alle_tiffs
mkdir -p losse_fotos

# Bepaal nette weergave voor de XMP-naam in de log
if [ -n "$xmp_file" ] && [ -f "$xmp_file" ]; then
    xmp_display="$(basename "$xmp_file")"
else
    xmp_display="Geen (standaard darktable profiel)"
fi

echo "------------------------------------------"
echo " Gekozen map:        $target_dir"
echo " Gekozen bitdiepte:  $BIT_DEPTH-bit"
echo " XMP-bestand:        $xmp_display"
echo " Maximaal per stack: $MAX_BURST_SIZE foto's"
echo "------------------------------------------"
echo "Bestanden inlezen en sorteren op tijd..."

mapfile -t sorted_files < <(
    exiftool -q -q -p '$DateTimeOriginal.$SubSecTimeOriginal|$directory/$filename' -d "%s" *.RW2 |
    sort -t'|' -k1,1n
)

total=${#sorted_files[@]}

if [ "$total" -eq 0 ]; then
    kdialog --sorry "Geen .RW2-bestanden gevonden in deze map."
    exit 0
fi

echo "Totaal ${total} RW2-bestanden gevonden. Bezig met analyseren..."

i=0
stack_counter=1

while [ $i -lt $total ]; do
    IFS='|' read -r t_start filepath <<< "${sorted_files[i]}"
    stack_files=("$filepath")

    j=$((i + 1))

    while [ $j -lt $total ] && [ ${#stack_files[@]} -lt $MAX_BURST_SIZE ]; do
        IFS='|' read -r t_prev _ <<< "${sorted_files[j-1]}"
        IFS='|' read -r t_curr curr_path <<< "${sorted_files[j]}"

        diff=$(awk "BEGIN {print $t_curr - $t_prev}")

        if awk "BEGIN {exit !($diff <= $TIME_THRESHOLD)}"; then
            stack_files+=("$curr_path")
            j=$((j + 1))
        else
            break
        fi
    done

    count=${#stack_files[@]}

    if [ $count -ge 3 ]; then
        echo "--> Stack $stack_counter gevonden ($count beelden)"

        # Bepaal de naam van de eerste foto uit de stack (zonder extensie)
        first_file_basename=$(basename "${stack_files[0]}")
        first_name_no_ext="${first_file_basename%.*}"
        output_filename="${first_name_no_ext}_stack.tif"

        stack_dir="stack_$(printf "%03d" $stack_counter)"
        mkdir -p "$stack_dir"

        # Kopieer de RW2 bestanden naar de stack-map
        for fp in "${stack_files[@]}"; do
            cp "$fp" "$stack_dir/"
        done

        cd "$stack_dir" || exit

        for rw2 in *.RW2; do
            base_name="${rw2%.*}"
            out_tiff="${base_name}.tif"
            echo "    Converteren via Darktable (XMP: $xmp_display): $rw2"

            if [ -n "$xmp_file" ] && [ -f "$xmp_file" ]; then
                darktable-cli "$rw2" "$xmp_file" "$out_tiff"
            else
                darktable-cli "$rw2" "$out_tiff"
            fi

            if [ "$BIT_DEPTH" -eq 8 ]; then
                mogrify -depth 8 "$out_tiff"
            fi
        done

        rm -f *.RW2

        echo "    Uitlijnen beelden..."
        alignment_output=$(align_image_stack -a aligned_ *.tif 2>&1)

        if echo "$alignment_output" | grep -q -E "too few control points|control points left|Strange values may result|No Feature Points|Exiting"; then
            echo "    [Let op] Uitlijnen mislukt door duisternis/laag contrast. We gaan direct door zonder uitlijning..."
            rm -f aligned_*.tif
            idx=0
            for tiff in *.tif; do
                [[ "$tiff" == aligned_* ]] && continue
                cp "$tiff" "aligned_$(printf "%04d" $idx).tif"
                idx=$((idx + 1))
            done
        else
            echo "$alignment_output"
        fi

        stack_input="aligned_*.tif"

        if [ $count -gt 5 ]; then
            echo "    Samenvoegen via Mean Stack (ImageMagick) vanwege $count beelden..."
            magick $stack_input -evaluate-sequence mean "../alle_tiffs/${output_filename}"
        else
            echo "    Samenvoegen met enfuse ($count beelden)..."
            enfuse --output="../alle_tiffs/${output_filename}" $stack_input
        fi

        echo "    --> Opgeslagen: ${output_filename}"
        cd ..

        rm -rf "$stack_dir"
        stack_counter=$((stack_counter + 1))
        i=$j
    else
        single_file="${stack_files[0]}"
        echo "Losse foto gedetecteerd: $(basename "$single_file") (wordt verplaatst)"
        mv "$single_file" losse_fotos/
        i=$((i + 1))
    fi
done

echo ""
echo "Klaar! Stacks verwerkt naar ./alle_tiffs en losse foto's verplaatst naar ./losse_fotos"
kdialog --msgbox "Klaar!\n\nAlle stacks zijn verwerkt en opgeslagen in:\n$target_dir/alle_tiffs"
