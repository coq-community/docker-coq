ARG BASE_TAG="latest"
FROM coqorg/base:${BASE_TAG}

ARG COQ_EXTRA_OPAM="coq-bignums"
ENV COQ_EXTRA_OPAM="${COQ_EXTRA_OPAM}"

ARG COQ_VERSION="dev"
ENV COQ_VERSION=${COQ_VERSION}

ARG COQ_COMMIT

# This line is actually unneeded (was already enabled in coqorg/base)
SHELL ["/bin/bash", "--login", "-o", "pipefail", "-c"]

# hadolint ignore=SC2046
RUN set -x \
  && eval $(opam env "--switch=${COMPILER_EDGE}" --set-switch) \
  && opam repository add --all-switches --set-default coq-extra-dev https://coq.inria.fr/opam/extra-dev \
  && opam repository add --all-switches --set-default coq-core-dev https://coq.inria.fr/opam/core-dev \
  && opam update -y -u \
  && opam pin add -n -y --lock-suffix=docker --locked -k git coq.${COQ_VERSION} "git+https://github.com/coq/coq#${COQ_COMMIT}" \
  && opam install -y -v -j "${NJOBS}" coq ${COQ_EXTRA_OPAM} \
  && opam clean -a -c -s --logs \
  && chmod -R g=u /home/coq/.opam \
  && opam config list && opam list

# hadolint ignore=SC2046
RUN set -x \
  && eval $(opam env "--switch=${COMPILER}"--set-switch) \
  && opam update -y -u \
  && opam pin add -n -y --lock-suffix=docker --locked -k git coq.${COQ_VERSION} "git+https://github.com/coq/coq#${COQ_COMMIT}" \
  && opam install -y -v -j "${NJOBS}" coq ${COQ_EXTRA_OPAM} \
  && opam clean -a -c -s --logs \
  && chmod -R g=u /home/coq/.opam \
  && opam config list && opam list

# Remark: The bash scripts above guarantee both opam switches have the
# same version of Coq; "opam pin add -n -k version coq ${COQ_VERSION}"
# (with COQ_VERSION=dev) would be too imprecise.

ARG BUILD_DATE
ARG VCS_REF
LABEL org.label-schema.build-date=${BUILD_DATE} \
  org.label-schema.name="The Coq Proof Assistant" \
  org.label-schema.description="Coq is a formal proof management system. It provides a formal language to write mathematical definitions, executable algorithms and theorems together with an environment for semi-interactive development of machine-checked proofs." \
  org.label-schema.url="https://coq.inria.fr/" \
  org.label-schema.vcs-ref=${VCS_REF} \
  org.label-schema.vcs-url="https://github.com/coq/coq" \
  org.label-schema.vendor="The Coq Development Team" \
  org.label-schema.version=${COQ_VERSION} \
  org.label-schema.schema-version="1.0" \
  maintainer="erik@martin-dorel.org"
