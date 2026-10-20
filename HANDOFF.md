# Handoff — Générateur TOTP sur HP 48G

## Objectif

Transformer une **HP 48G** (1993, 32 Ko de RAM, CPU Saturn 4 bits ~4 MHz) en **token 2FA hors ligne** : elle affiche les codes TOTP (RFC 6238, HMAC-SHA1, 6 chiffres, pas de 30 s) compatibles avec Google Authenticator, à partir de son horloge interne.

Usage visé : sauvegarde « air-gapped » des codes 2FA, utilisable même si le téléphone est perdu.

Contraintes :
- 32 Ko de RAM seulement (pas de ports d'extension sur la 48G).
- Pas de communication réseau : le secret est chargé une fois via le câble série.
- Projet de loisir à temps limité : chaque étape doit produire un résultat utilisable et testable seul.

## État (21/10/2026)

Toutes les étapes sont faites et l'app tourne sur la vraie 48G (9 comptes importés depuis Ente Auth). Le mode d'emploi et la documentation technique à jour sont dans le [README](README.md) ; ce document garde le plan d'origine.

| Étape | Résultat |
|---|---|
| 0 — Outillage | HP Tools 3.0.8 compilés sous Fedora ; x48ng (tests automatisés) et Emu48 sous Wine (manuel) ; câble USB-RS232 Prolific opérationnel |
| 1 — Référence Python | `ref/` : vecteurs RFC 4226/6238 validés par HMAC et par midstates |
| 2 — Horloge | `rpl/UNIX.hp` (`CNT` intégré à l'app) |
| 3 — SHA-1 en assembleur | `asm/sha1.a`, vérifié ronde par ronde contre `sha1_trace.py` (~8 800 instructions) |
| 4 — HMAC et troncature | `asm/hotp.a`, objet Code sans appel ROM (~0,05 s par code) |
| 5 — Programme final | `rpl/OTP.hp` : un écran par compte, gros chiffres, décompte, touches PREV/NEXT/TZ/QUIT |

Écarts par rapport au plan :
- Transfert : C-Kermit ne fonctionne pas avec l'émulateur, remplacé par `tools/hpkermit.py` (client Kermit minimal, aussi utilisé avec le vrai câble).
- Charge utile : `ACCTS` regroupe tous les comptes (`{ { "nom" { 10 entiers binaires } } … }`) au lieu d'une variable par compte ; import des exports `otpauth://` (Ente Auth, Aegis).
- Hôte : Fedora (`dnf install ckermit`) plutôt que Debian.

## Stack (plan d'origine)

| Élément | Choix |
|---|---|
| Machine hôte | Linux (Debian/Ubuntu ou Raspberry Pi OS) |
| Lien calculatrice | Câble série maison (voir annexe) + adaptateur USB–RS-232 → `/dev/ttyUSB0` |
| Transfert | C-Kermit (`ckermit`), 9600 bauds |
| Référence / outils | Python 3 (stdlib : `hashlib`, `hmac`, `base64`, `struct`) |
| Code calculatrice | User RPL (colle, horloge, affichage) + assembleur Saturn (compression SHA-1) |
| Émulateur | À déterminer à l'étape 0 (piste : x48ng sous Linux, ou Emu48/Debug4x sous Wine) |

## Faits techniques à respecter

**Algorithme TOTP**
1. `counter = floor(unix_time / 30)`, encodé sur 8 octets big-endian.
2. `h = HMAC-SHA1(secret, counter)` → 20 octets.
3. `offset = h[19] & 0x0F` ; `code = (int.from_bytes(h[offset:offset+4]) & 0x7FFFFFFF) % 10**6`.

**Optimisation clé : midstates HMAC**
Le secret ne change jamais. On précalcule sur le PC :
- `istate = SHA1_compress(IV, (key_padded XOR ipad))`
- `ostate = SHA1_compress(IV, (key_padded XOR opad))`

Sur la calculatrice, chaque code ne demande alors que **2 compressions** au lieu de 4 :
- interne : `compress(istate, counter(8 o) || padding)`, longueur totale déclarée = 72 octets (576 bits) ;
- externe : `compress(ostate, inner_hash(20 o) || padding)`, longueur totale déclarée = 84 octets (672 bits).

Les midstates sont aussi sensibles que le secret lui-même.

**Heure Unix sur la 48G** (programme User RPL, `TZ` = décalage UTC en heures, stocké dans une variable) :
```
« 1.011970 DATE DDAYS 86400 * TIME HMS→ 3600 * + TZ 3600 * - 30 / IP »
```
`1.011970` vaut 1er janvier 1970 dans les deux formats de date de la 48G. France : `TZ` = 2 en heure d'été, 1 en heure d'hiver (à changer à la main).

**Saturn / assembleur**
- Registres 64 bits ; travailler en 32 bits avec `P=7` et le champ `WP` (nibbles 0 à 7).
- **Pas d'instruction XOR** : la construire avec AND, OR, NOT (macro serrée, très utilisée).
- Décalages par nibble (`ASL`, `ASR`…) et par bit (`ASRB`…) ; rotations SHA-1 à composer sans déborder du champ 32 bits.
- Mémoire lue nibble de poids faible en premier ; SHA-1 est big-endian → permuter chaque mot au chargement et au stockage.
- Mode hexadécimal (`SETHEX`) pour l'arithmétique.

**En User RPL (si besoin d'une version de secours)**
`32 STWS` puis entiers binaires : `+` boucle modulo 2³², `AND OR XOR NOT` disponibles, rotations `RL`, `RR`, `RLB`, `RRB` (rotl5 = `RLB RR RR RR`, rotl30 = `RR RR`). Ordre de grandeur : un SHA-256 en User RPL prend ~80 s sur une 48G réelle, donc une version tout-RPL dépasserait probablement une minute par code.

**Vecteurs de test**
- RFC 4226 (HOTP), secret ASCII `12345678901234567890`, compteur 0 → `755224`.
- RFC 6238 (TOTP SHA-1), même secret, T = 59 s → `94287082` (8 chiffres) soit `287082` en 6 chiffres.

## Étapes

Chaque étape a un livrable et un critère de réussite.

### Étape 0 — Lien et outillage
- Configurer Kermit (annexe), vérifier le transfert d'un fichier texte vers la calculatrice et retour.
- Choisir et installer un émulateur HP 48G/GX sous Linux, avec une ROM légalement obtenue (dump de la calculatrice de l'utilisateur, ou ROM distribuée avec l'autorisation de HP si hpcalc.org le confirme).
- Choisir une chaîne d'assemblage Saturn utilisable sous Linux (outils HP sous Wine/DOSBox, GNU Tools for HP48, ou autre) et assembler un « hello world » en code machine appelable depuis RPL.
- **Réussite :** un objet assemblé sur le PC tourne dans l'émulateur.

### Étape 1 — Référence Python (`ref/`)
- `totp_ref.py` : TOTP/HOTP, validés sur les vecteurs RFC.
- `sha1_trace.py` : SHA-1 maison qui imprime l'état (a, b, c, d, e) après chaque ronde, pour déboguer l'assembleur ronde par ronde.
- `make_hp_payload.py` : prend un secret base32 (format des QR codes 2FA), calcule `istate`/`ostate`, et génère un fichier HP (`%%HP: T(3)A(D)F(.);`, avec `\<<`, `\>>`, `\->` pour « » →) prêt à envoyer par Kermit.
- **Réussite :** tous les vecteurs RFC passent ; le payload se charge sur la calculatrice.

### Étape 2 — Horloge et compteur (`rpl/`)
- Programme `UNIX` (variante sans `30 / IP`) et `CNT` (compteur TOTP), variable `TZ`.
- **Réussite :** `UNIX` correspond à l'heure Unix réelle à quelques secondes près ; ajuster l'horloge de la 48G si besoin.

### Étape 3 — Compression SHA-1 en assembleur (`asm/`)
- Entrée : un état de 5 mots + un bloc de 64 octets ; sortie : nouvel état de 5 mots.
- Développer et tester **uniquement dans l'émulateur**, en comparant à `sha1_trace.py`.
- **Réussite :** sortie identique à Python sur plusieurs blocs, dont les deux blocs HMAC du vecteur RFC.

### Étape 4 — HMAC et troncature
- Assembler les deux compressions avec les midstates, puis troncature dynamique et modulo 10⁶ (en RPL, c'est peu coûteux).
- **Réussite :** le vecteur RFC 6238 à T = 59 donne `287082`, en passant le compteur à la main.

### Étape 5 — Programme final
- Lecture de l'horloge → compteur → code, affichage du code à 6 chiffres et des secondes restantes (`30 - (unix mod 30)`).
- Optionnel : plusieurs comptes (une paire de midstates par compte, choix dans un menu `TMENU`).
- **Interface retenue (20/10/2026)** : écran plein par compte, nom du compte + n°/total + fuseau (CET/CEST) en haut, code en gros chiffres, barre de décompte et secondes restantes rafraîchies chaque seconde ; touches PREV / NEXT / TZ (bascule 1↔2) / QUIT, ON quitte aussi.
- **Réussite :** dans l'émulateur puis sur la vraie calculatrice, codes identiques à une appli d'authentification pour un compte de test.

## Sécurité et précautions

- **Sauvegarder toute la mémoire de la vraie calculatrice** (via Kermit) avant d'y exécuter du code assembleur : un bug peut provoquer un « Memory Clear ».
- Ne jamais committer de vrai secret 2FA ni de midstates dans le dépôt ; utiliser le secret RFC pour tous les tests.
- La calculatrice n'offre aucune protection : quiconque l'a en main peut lire les variables. À traiter comme une clé.
- L'horloge de la 48G dérive : la plupart des services acceptent ±1 fenêtre de 30 s, mais il faut la recaler de temps en temps.

## Antériorité

Pas de TOTP connu sur HP 48. Des implémentations existent sur TI-84 Plus (assembleur Z80, 2021) et TI-89 / Voyage 200 (2021). Sur HP 48G : SHA-256 en User RPL (2023) et S/KEY sur hpcalc.org, à consulter pour les techniques de hachage.

## Structure de dépôt suggérée

```
hp48-totp/
├── HANDOFF.md
├── ref/        # Python : référence, traces, génération du payload
├── rpl/        # sources User RPL en texte (format %%HP)
├── asm/        # sources Saturn
├── tools/      # config Kermit, scripts d'envoi
└── Makefile    # build asm, envoi vers émulateur / calculatrice
```

## Annexe — Câble et Kermit

**Câble.** Connecteur JST PH 2.0 à 4 broches (limé, dans le boîtier imprimé Printables 380219) → adaptateur USB–RS-232 en vrais niveaux RS-232 (pas TTL).
Broches HP numérotées de l'extérieur vers l'intérieur :
- 2 (TX HP) → RX du PC (broche 2 d'une DB9, ou pointe du jack sur le câble Usangreen)
- 3 (RX HP) → TX du PC (broche 3 de la DB9, ou anneau du jack)
- 4 (masse) → broche 5 de la DB9, ou manchon du jack
- 1 (blindage) : libre

Si rien ne passe, inverser les fils 2 et 3 en premier.

**`~/.kermrc`**
```
set line /dev/ttyUSB0
set speed 9600
set parity none
set flow none
set carrier-watch off
set modem type direct
set block-check 3
set file type binary
```
Prérequis (Fedora) : `sudo dnf install ckermit` et `sudo usermod -aG dialout $USER` (puis se reconnecter).

**Côté HP 48G** : menu I/O (shift droit + 1) → Wire, 9600 bauds, parité aucune, checksum 3, translate code 3 ; lancer le serveur. Puis sur le PC : `send FICHIER`, `get NOM`, `finish`.
