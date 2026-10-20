PY ?= python3

.PHONY: test vectors trace payload-rfc payload-rfc-emu emu emu-rpl

test:
	cd ref && $(PY) -m unittest -v test_ref

vectors:
	cd ref && $(PY) totp_ref.py test

trace:
	cd ref && $(PY) sha1_trace.py rfc

payload-rfc:
	cd ref && $(PY) make_hp_payload.py --name KT --rfc

payload-rfc-emu:
	cd ref && $(PY) make_hp_payload.py --name KT --rfc --emu

emu:
	sh tools/emu48.sh

# rpl/NAME.hp -> out/NAME.txt for Emu48's Load Object (then OBJ->)
emu-rpl: $(patsubst rpl/%.hp,out/%.txt,$(wildcard rpl/*.hp))

out/%.txt: rpl/%.hp tools/hp2emu.py
	@mkdir -p out
	$(PY) tools/hp2emu.py $< $@
