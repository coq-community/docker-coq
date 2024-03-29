#!/usr/bin/env bash
# Author: Erik Martin-Dorel, 2020-2021
# Summary: helper functions to compute compatible OCaml versions

ocamls() { opam switch list-available ocaml-base-compiler | grep -v -e '#' | cut -d ' ' -f 2; }

pred_ocaml_for_coqs() {
    for v; do
	printf '%s' "* Coq $v: "'`'
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
	printf '%s' "* Coq $v: "
	if [ "$v" = "8.4.6" ] || [ "$v" = "8.5.3" ] || [ "$v" = "8.6.1" ]; then
	    minimal="4.02.3"
	    default="4.02.3"
	    several='false'
	else
	    versions=$(opam search ocaml-base-compiler --no-switch --columns=version -V --coinstallable-with="coq.$v" | grep -v -e '#' -e 'alpha' -e 'beta' -e 'rc' -e '4\.09\.0')
	    if [[ "$versions" =~ 4\.05\.0 ]]; then
		minimal="4.05.0"
	    else
		minimal="$(head -n 1 <<<"$versions")-flambda"
	    fi
            # BEGIN SWAP THIS LATER ON IF NEED BE
            if [[ "$versions" =~ 4\.07\.1 ]]; then
		default="4.07.1-flambda"
	    elif [[ "$versions" =~ 4\.13\.1 ]]; then
		default="4.13.1-flambda"  # like Coq Platform
            # END SWAP THIS LATER ON IF NEED BE
	    else
		default="$minimal"
	    fi
	fi
	[ "$render" = 'true' ] && printf '\n%s' "${indent}default: ['"
	if [ "$render" = 'true' ]; then
	    printf '%s' "$default"
	else
	    printf '%s' "$minimal"
	fi
	[ "$render" = 'true' ] && printf "']\n"
	[ "$render" = 'true' ] && printf '%s' "${indent}base: ["
	if [ "$several" = 'true' ]; then
	    minor2=$(cut -d '.' -f 1-2 <<<"$versions" | sort -u -V | tail -n 2 | tac)
	    minor3=$(cut -d '.' -f 1-2 <<<"$versions" | sort -u -V | tail -n 3 | tac)
	    last2=$(for vv in $minor2; do grep -e "^${vv//./\\.}.*\$" <<<"$versions" | tail -n 1; done)
	    last3=$(for vv in $minor3; do grep -e "^${vv//./\\.}.*\$" <<<"$versions" | tail -n 1; done)
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
                    printf '%s' "$last3" | xargs printf "'%s-flambda', "
                    # SHOULD check that default notin last3
                else
                    printf '%s' "$last2" | xargs printf "'%s-flambda', "
                    printf '%s' "$default" | xargs printf "'%s', "
                    # SHOULD check that default notin last2
                fi
            else
                if [ "$already" = 'true' ]; then
                    printf '%s' "$last3" | xargs printf "%s-flambda "
                else
                    printf '%s' "$last2" | xargs printf "%s-flambda "
                    printf '%s' "$default" | xargs printf "%s "
                fi
	    fi
        fi
	[ "$render" = 'true' ] && printf '%s' "'$minimal']"
	printf "\n"
	[ "$render" = 'true' ] && printf '%s\n ' "${indent}coq: ['${v}']"
    done
}

# opam repo add --all-switches --set-default coq-core-dev https://coq.inria.fr/opam/core-dev
# opam update
# opam show coq
# pred_ocaml_for_coqs 8.4.6 8.5.3 8.6.1 8.7.2 8.8.2 8.9.1 8.10.2 8.11.2 8.12.2 8.13.2 8.14.1 8.15.2 dev
# list_ocaml_for_coqs dev 8.15.2 8.14.1 8.13.2 8.12.2 8.11.2 8.10.2 8.9.1 8.8.2 8.7.2 8.6.1 8.5.3 8.4.6
