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
		minimal="$(head -n 1 <<<"$versions")-flambda"
	    fi
            # BEGIN SWAP THIS LATER ON IF NEED BE
            if [[ "$versions" =~ "4.07.1" ]]; then
		default="4.07.1-flambda"
	    elif [[ "$versions" =~ "4.13.1" ]]; then
		default="4.13.1-flambda"  # like Coq Platform
            # END SWAP THIS LATER ON IF NEED BE
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
	    minor2=$(cut -d '.' -f 1-2 <<<"$versions" | sort -u -V | tail -n 2)
	    minor3=$(cut -d '.' -f 1-2 <<<"$versions" | sort -u -V | tail -n 3)
	    last2=$(for v in $minor2; do grep -e "^${v//./\\.}.*\$" <<<"$versions" | tail -n 1; done)
	    last3=$(for v in $minor3; do grep -e "^${v//./\\.}.*\$" <<<"$versions" | tail -n 1; done)
            dflt_regex="${default%-flambda}"
            dflt_regex="${dflt_regex//./\\.}"
            # Incomplete algorithm (to be refined):
            # we check that default is not in {minimal} \/ last3
            already=$(if grep -q -e "^${dflt_regex}$" <<< "$minimal" || \
                          grep -q -e "^${dflt_regex}$" <<< "$last3"; then
                          echo true
                      else
                          echo false
                      fi)
            if [ "$render" = 'true' ]; then
                if [ "$already" = 'true' ]; then
                    printf '%s' "$last3" | xargs printf ", '%s-flambda'"
                    # SHOULD check that default notin last3
                else
                    printf '%s' "$default" | xargs printf ", '%s'"
                    printf '%s' "$last2" | xargs printf ", '%s-flambda'"
                    # SHOULD check that default notin last2
                fi
            else
                if [ "$already" = 'true' ]; then
                    printf '%s' "$last3" | xargs printf " %s-flambda"
                else
                    printf '%s' "$default" | xargs printf " %s"
                    printf '%s' "$last2" | xargs printf " %s-flambda"
                fi
	    fi
        fi
	[ "$render" = 'true' ] && printf "]"
	printf "\n"
	[ "$render" = 'true' ] && printf "${indent}coq: ['${v}']\n"
    done
}

# opam repo add --all-switches --set-default coq-core-dev https://coq.inria.fr/opam/core-dev
# opam update
# opam show coq
# pred_ocaml_for_coqs 8.4.6 8.5.3 8.6.1 8.7.2 8.8.2 8.9.1 8.10.2 8.11.2 8.12.2 8.13.2 8.14.1 8.15.2 dev
# list_ocaml_for_coqs dev 8.15.2 8.14.1 8.13.2 8.12.2 8.11.2 8.10.2 8.9.1 8.8.2 8.7.2 8.6.1 8.5.3 8.4.6
