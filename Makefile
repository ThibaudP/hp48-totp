PY ?= python3
HPTOOLS ?= $(HOME)/.local/share/hp48-emu/hptools/bin
X48NG_SRC ?= $(HOME)/.local/share/hp48-emu/src/x48ng/src
SATRUN = tools/satrun/satrun

.PHONY: test vectors trace payload-rfc app emu emu-rpl asm satrun asm-test e2e

test:
	cd ref && $(PY) -m unittest -v test_ref

vectors:
	cd ref && $(PY) totp_ref.py test

trace:
	cd ref && $(PY) sha1_trace.py rfc

payload-rfc:
	cd ref && $(PY) make_hp_payload.py --rfc

# out/TOTP: the app directory (RPL programs + big digit font) in text form
app:
	$(PY) tools/build_app.py

emu:
	sh tools/emu48.sh

# rpl/NAME.hp -> out/NAME.txt for Emu48's Load Object (then OBJ->)
emu-rpl: $(patsubst rpl/%.hp,out/%.txt,$(wildcard rpl/*.hp))

out/%.txt: rpl/%.hp tools/hp2emu.py
	@mkdir -p out
	$(PY) tools/hp2emu.py $< $@

# asm/NAME.a + asm/NAME.m -> asm/NAME.bin (HPHP48 binary object, Load Object in Emu48)
asm: $(patsubst %.a,%.bin,$(wildcard asm/*.a))

asm/%.bin: asm/%.a asm/%.m
	cd asm && $(HPTOOLS)/sasm $*.a && $(HPTOOLS)/sload -H $*.m > /dev/null

# x48ng's Saturn CPU core with flat memory, for unit-testing asm routines
satrun: $(SATRUN)

$(SATRUN): tools/satrun/satrun.c $(X48NG_SRC)/core/emulate.c $(X48NG_SRC)/core/registers.c
	$(CC) -O2 -w -I$(X48NG_SRC) -o $@ $^

asm-test: asm $(SATRUN)
	cd asm && $(PY) -m unittest discover -v -p 'test_*.py'

# boots x48ng headless, talks to it over the emulated wire port (slow, ~1 min)
e2e: asm app
	$(PY) -m unittest -v tests/test_e2e.py tests/test_app.py
