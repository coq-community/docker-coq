#!/usr/bin/env bash
# Author: Erik Martin-Dorel, 2020-2021
# Summary: helper functions to compute compatible OCaml versions

ocamls() { opam switch list-available ocaml-base-compiler | grep -v -e '#' | cut -d ' ' -f 2; }

pred_ocaml_for_coqs() {
    for v; do
	printf "* Coq $v: "'`'
	printf '%s' "$(opam show "coq.$v" -f depends: | grep '"ocaml"')"
	printf '`\n'
    done
}

list_ocaml_for_coqs() {
    local indent='      '
    # To change manually:
    local render='true'
    # local render='false'
    # Note: we may post-process the output to merge "coq" items with same ocaml
    for v; do
	local several='true'
	printf "* Coq $v: "
	if [ "$v" = "8.4.6" ] || [ "$v" = "8.5.3" ] || [ "$v" = "8.6.1" ]; then
	    minimal="4.02.3"
	    default="4.02.3"
	    several='false'
	else
	    versions=$(opam search ocaml-base-compiler --no-switch --columns=version -V --coinstallable-with="coq.$v" | grep -v -e '#' -e 'alpha' -e 'beta' -e 'rc')
	    if [[ "$versions" =~ "4.05.0" ]]; then
		minimal="4.05.0"
	    else
		minimal=$(head -n 1 <<<"$versions")
	    fi
	    if [[ "$versions" =~ "4.07.1" ]]; then
		default="4.07.1-flambda"
	    else
		default="$minimal"
	    fi
	fi
	[ "$render" = 'true' ] && printf "\n${indent}default: ['"
	if [ "$render" = 'true' ]; then
	    printf "$default"
	else
	    printf "$minimal"
	fi
	[ "$render" = 'true' ] && printf "']\n"
	[ "$render" = 'true' ] && printf "${indent}base: ['$minimal'"
	if [ "$several" = 'true' ]; then
	    if [[ "$versions" =~ "4.07.1" ]]; then
		if [ "$render" = 'true' ]; then
		    printf ", '4.07.1-flambda'"
		else
		    printf " 4.07.1-flambda"
		fi
	    fi
	    minor=$(cut -d '.' -f 1-2 <<<"$versions" | sort -u -V | tail -n 2)
	    lasttwo=$(for v in $minor; do grep -e "^${v//./\\.}.*\$" <<<"$versions" | tail -n 1; done)
	    maybelasttwo=$(grep -v -e "^${minimal//./\\.}\$" -e '^4\.07$' <<<"$lasttwo")
	    if [ "$render" = 'true' ]; then
		printf '%s' "$maybelasttwo" | xargs printf ", '%s-flambda'"
	    else
		printf '%s' "$maybelasttwo" | xargs printf " %s-flambda"
	    fi
	fi
	[ "$render" = 'true' ] && printf "]"
	printf "\n"
	[ "$render" = 'true' ] && printf "${indent}coq: ['${v}']\n"
    done
}

# pred_ocaml_for_coqs 8.4.6 8.5.3 8.6.1 8.7.2 8.8.2 8.9.1 8.10.2 8.11.2 8.12.2 8.13.2 8.14.dev # 8.14-alpha 
# list_ocaml_for_coqs 8.14.dev 8.13.2 8.12.2 8.11.2 8.10.2 8.9.1 8.8.2 8.7.2 8.6.1 8.5.3 8.4.6
