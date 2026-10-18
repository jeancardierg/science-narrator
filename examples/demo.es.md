---
title: La mitocondria en 60 segundos
language: es
voice: ../voices/voice.wav       # tu muestra (no se sube a git)
lexicon: [lexicon.es.yaml]
fps: 25                          # sólo para timecodes con frames HH:MM:SS:FF
# exaggeration: 0.35  cfg_weight: 0.55  temperature: 0.5  takes: 3
---
<!--
Formato:
  [HH:MM:SS.mmm]                 el segmento empieza en ese instante del vídeo
  [inicio -> fin]                el segmento debe caber en ese hueco
  [+] / [+0.8]                   justo después del anterior (+ hueco en s)
  key=value en la línea del cue  ajustes por segmento: exaggeration= cfg= temperature= seed= takes= language=
  [término|pronunciación]        corrige la pronunciación sólo aquí
  {pause 0.6}                    pausa explícita
  línea en blanco                pausa de párrafo
-->

[00:00:01.000] intro
¿De dónde sale la energía que usa cada una de tus células? {pause 0.4}
De un orgánulo diminuto: la mitocondria.

[00:00:08.500 -> 00:00:22.000] tamaño
Mide entre 0,5–1 µm, y una sola célula del hígado puede tener más de 2.000.
Dentro, una cadena de proteínas bombea protones a través de su membrana interna.

[00:00:23.000] atp exaggeration=0.45
Ese gradiente mueve una turbina molecular, la [ATP sintasa|a te pe sintasa], que fabrica ATP.
Cada día, tu cuerpo produce y recicla aproximadamente su propio peso en ATP.

[+0.8] cierre seed=99
Sin mitocondrias, no habría ADN de ningún animal complejo que lo pudiera contar.
