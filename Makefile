PY ?= python3
# Local toolchain (scripts/setup-toolchain.sh builds it there)
export HP48_EMU_HOME ?= $(HOME)/.local/share/hp48-emu
HPTOOLS ?= $(HP48_EMU_HOME)/hptools/bin
X48NG_SRC ?= $(HP48_EMU_HOME)/src/x48ng/src
SATRUN = tools/satrun/satrun
# x48ng's headers include Lua's (Fedora: lua-devel, Debian/Ubuntu: liblua5.4-dev)
LUA_CFLAGS ?= $(shell pkg-config --cflags lua5.4 2>/dev/null || pkg-config --cflags lua 2>/dev/null)

.PHONY: help toolchain check dist test vectors trace payload-rfc app emu emu-rpl asm satrun asm-test e2e clean

help:
	@echo "make toolchain   build HP Tools, x48ng and fetch the ROM into $(HP48_EMU_HOME)"
	@echo "make check       Python reference tests + Saturn asm tests (fast)"
	@echo "make e2e         end-to-end tests on a headless emulated 48GX (~3.5 min)"
	@echo "make asm app     build the machine code (asm/*.bin) and the app directory (out/TOTP)"
	@echo "make dist        dist/TOTP: the whole app as one binary file (built on the emulator)"
	@echo "make clean       remove build products"

toolchain:
	scripts/setup-toolchain.sh

check: test asm-test

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
	$(CC) -O2 -w -I$(X48NG_SRC) $(LUA_CFLAGS) -o $@ $^

asm-test: asm $(SATRUN)
	cd asm && $(PY) -m unittest discover -v -p 'test_*.py'

# boots x48ng headless, talks to it over the emulated wire port (~3.5 min)
e2e: asm app dist
	$(PY) -m unittest -v tests/test_e2e.py tests/test_app.py tests/test_dist.py

# dist/TOTP: install the app on the emulator, fetch the directory back in binary
dist: asm app
	$(PY) tools/build_dist.py

clean:
	rm -f asm/*.o asm/*.l asm/*.bin $(SATRUN) out/TOTP out/*.txt
	rm -rf __pycache__ */__pycache__
