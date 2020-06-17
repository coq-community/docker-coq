ARG BASE_IMAGE="coqorg/base:latest"
FROM ${BASE_IMAGE}

ARG COQ_EXTRA_OPAM="coq-bignums"
ENV COQ_EXTRA_OPAM="${COQ_EXTRA_OPAM}"

ARG COQ_VERSION="dev"
ENV COQ_VERSION=${COQ_VERSION}

RUN ["/bin/bash", "--login", "-c", "set -x \
  && eval $(opam env --switch=${COMPILER_EDGE} --set-switch) \
  && opam update -y -u \
  && opam pin add -n -k version coq ${COQ_VERSION} \
  && opam install -y -v -j ${NJOBS} coq ${COQ_EXTRA_OPAM} \
  && opam clean -a -c -s --logs \
  && opam config list && opam list"]

RUN ["/bin/bash", "--login", "-c", "set -x \
  && eval $(opam env --switch=${COMPILER} --set-switch) \
  && opam update -y -u \
  && opam pin add -n -k version coq ${COQ_VERSION} \
  && opam install -y -v -j ${NJOBS} coq ${COQ_EXTRA_OPAM} \
  && opam clean -a -c -s --logs \
  && opam config list && opam list"]

LABEL maintainer="erik@martin-dorel.org"
