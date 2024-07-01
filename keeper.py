#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020-2024  Érik Martin-Dorel
#
# Contributed under the terms of the MIT license,
# cf. <https://spdx.org/licenses/MIT.html>

from bash_formatter import BashLike
from datetime import datetime
from itertools import chain
import argparse
import base64
import copy
import json
import requests
import os
import re
import sys
import time
import yaml

prog = os.path.basename(__file__)
output_directory = 'generated'
images_filename = 'images.yml'
json_indent = 2
upstream_project = 'erikmd/docker-keeper'
upstream_url = 'https://gitlab.com/%s' % upstream_project
desc = """
§ docker-keeper

This python3 script is devised to help maintain Docker Hub repositories of
stable and dev (from webhooks or for nightly builds) Docker images from a
YAML-specified, single-branch Git repository - typically created as a fork of
the following GitLab repo: <https://gitlab.com/erikmd/docker-keeper-template>.
For more details, follow the instructions of the README.md in your own fork.
Note: this script is meant to be run by GitLab CI.

docker-keeper offers customizable propagate strategies (declarative cURL calls)

It supports both single modes given in variable CRON_MODE (and optionally ITEM)
and multiple modes, from CLI as well as from HEAD's commit message, typically:
$ git commit --allow-empty -m "…" -m "docker-keeper: rebuild-all"
$ git commit -m "docker-keeper: propagate: I1: minimal; propagate: I2: nightly"
$ git commit -m "docker-keeper: propagate: ID: rebuild-all"
$ git commit -m "docker-keeper: propagate: ID: rebuild-keyword: KW1,KW2"
$ git commit -m "docker-keeper: propagate: ()"
If the commit message (or equivalently, the CLI) contains propagate…,
then it overrides the automatic default propagation.
If the commit is rebuilt with the same SHA1 in a given branch,
then it switches to the default behavior (automatic propagate strategy)."""


def print_stderr(message):
    print(message, file=sys.stderr, flush=True)


def dump(data):
    """Debug"""
    print_stderr(json.dumps(data, indent=json_indent))


# def error(msg, flush=True):
#     print(msg, file=sys.stderr, flush=flush)
#     exit(1)

class Error(Exception):
    """Base class for exceptions in this module."""
    pass


def error(msg):
    raise Error(msg)


def first_shortest_tag(list_tags):
    return sorted(list_tags, key=(lambda s: (len(s), s)))[0]


def uniqify(s):
    """Remove duplicates and sort the result list."""
    return sorted(set(s))


def uniqify_tags(list_tags):
    """Might be improved to mimic 'sort -V'"""
    return sorted(set(list_tags), key=(lambda s: (len(s), s)))


def diff_list(l1, l2):
    """Compute the set-difference (l1 - l2), preserving duplicates."""
    return list(filter(lambda e: e not in l2, l1))


def meet_list(l1, l2):
    """Return the sublist of l1, intersecting l2."""
    return list(filter(lambda e: e in l2, l1))


def subset_list(l1, l2):
    """Check if l1 is included in l2."""
    return not diff_list(l1, l2)


def is_unique(s):
    """Check if the list s has no duplicate."""
    return len(s) == len(set(s))


def merge_dict(a, b):
    """Merge the fields of a and b, the latter overriding the former."""
    res = copy.deepcopy(a) if a else {}
    copyb = copy.deepcopy(b) if b else {}
    for key in copyb:
        res[key] = copyb[key]
    return res


def check_domain(text):
    if not re.match(r'^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)+$',
                    text):
        error("Error: '%s' is not a valid domain name." % text)


def check_string(value, ident=None):
    if not isinstance(value, str):
        if ident:
            error("Error: expecting a string value, but was given '%s: %s'."
                  % (ident, value))
        else:
            error("Error: expecting a string value, but was given '%s'."
                  % value)


def check_list(value, text=None):
    if not isinstance(value, list):
        if not text:
            text = str(value)
        error("Error: not (JSON) list\nText: %s"
              % text)


def check_dict(value, text=None):
    if not isinstance(value, dict):
        if not text:
            text = str(value)
        error("Error: not (JSON) dict\nText: %s"
              % text)


def ignore_fields(obj, lst):
    for field in lst:
        obj.pop(field, None)


def check_no_fields(text, obj):
    if obj:
        print_stderr('Unexpected fields in %s:' % text)
        dump(obj)
        exit(1)


def remove_spaces(text):
    return text.replace(' ', '')


def trim_comma_split(text):
    """Turn a comma-separated string into a list of nonempty strings"""
    check_string(text)
    # the filter is useful to drop empty strings (e.g., for '8.19,8.20,')
    return list(filter(lambda e: e, remove_spaces(text).split(',')))


def flat_map_trim_comma_split(lst):
    """Apply trim_comma_split to each list elt then flatten; needs itertools"""
    if lst:
        return list(chain(*map(trim_comma_split, lst)))
    else:  # lst = None
        return []


def subset_comma_list(cstr1, cstr2):
    """Check if cstr1 is included in cstr2."""
    return subset_list(trim_comma_split(cstr1), trim_comma_split(cstr2))


def eval_bashlike(template, matrix, gvars=None, defaults=None):
    b = BashLike()
    return b.format(template, matrix=matrix, vars=gvars, defaults=defaults)


def eval_bashlike2(expr, matrix, tags, keywords):
    b = BashLike()
    return b.format(expr, matrix=matrix, tags=tags, keywords=keywords)


def eval_propagate(expr, build_elt):
    return eval_bashlike2(expr, build_elt['matrix'], build_elt['tags'],
                          build_elt['keywords'])


def uniq_cat_eval_propagate(expr, build_data):
    list_str = list(map(lambda elt: eval_propagate(expr, elt), build_data))
    return uniqify_tags(flat_map_trim_comma_split(list_str))


def get_build_date():
    """ISO 8601 UTC timestamp"""
    return datetime.utcnow().strftime("%FT%TZ")


def naive_url_encode(name):
    """https://gitlab.com/help/api/README.md#namespaced-path-encoding"""
    check_string(name)
    return name.replace('/', '%2F')


def gitlab_lambda_query_sha1(response):
    """Return the "commit.id" field from 'response.json()'."""
    return response.json()['commit']['id']


def lambda_query_text(response):
    return response.text


def get_url(url, headers=None, params=None, lambda_query=(lambda r: r)):
    """Some examples of lambda_query:

        - gitlab_lambda_query_sha1
        - lambda_query_text
    """
    print_stderr('GET %s\n' % url)
    response = requests.get(url, headers=headers, params=params)
    if not response:
        error("Error!\nCode: %d\nText: %s"
              % (response.status_code, response.text))
    return lambda_query(response)


def get_commit(commit_api):
    """Get GitHub or GitLab SHA1 of a given branch."""
    fetcher = commit_api['fetcher']
    repo = commit_api['repo']
    branch = commit_api['branch']
    if fetcher == 'github':
        url = 'https://api.github.com/repos/%s/commits/%s' % (repo, branch)
        headers = {"Accept": "application/vnd.github.v3.sha"}
        lambda_query = lambda_query_text
    elif fetcher == 'gitlab':
        # https://gitlab.com/help/api/branches.md#get-single-repository-branch
        url = ('https://gitlab.com/api/v4/projects/%s/repository/branches/%s'
               % (naive_url_encode(repo), naive_url_encode(branch)))
        headers = None
        lambda_query = gitlab_lambda_query_sha1
    else:
        error("Error: do not support 'fetcher: %s'" % fetcher)
    return get_url(url, headers, None, lambda_query)


def load_spec():
    """Parse the YAML file and return a dict."""
    print_stderr("Loading '%s'..." % images_filename)
    with open(images_filename) as f:
        j = yaml.safe_load(f)
    if 'active' not in j or not j['active']:
        print_stderr("""
WARNING: the 'docker-keeper' tasks are not yet active.
Please update your %s specification and Dockerfile templates.
Then, set the option 'active: true' in the %s file."""
                     % (images_filename, images_filename))
        exit(1)
    return j


def product_build_matrix(matrix):
    """Get the list of dicts grouping 1 item per list mapped to matrix keys."""
    assert matrix
    old = [{}]
    res = []
    for key in matrix:
        for value in matrix[key]:
            for e in old:
                enew = copy.deepcopy(e)
                enew[key] = value
                res.append(enew)
        old = res
        res = []
    return old


def check_trim_relative_path(path):
    """Fail if path is absolute and remove leading './'."""
    check_string(path)
    if path[0] == '/':
        error("Error: expecting a relative path, but was given '%s'." % path)
    elif path[:2] == './':
        return path[2:]
    else:
        return path


def check_filename(filename):
    check_string(filename)
    if '/' in filename:
        error("Error: expecting a filename, but was given '%s'." % filename)


def eval_if(raw_condition, matrix, gvars):
    """Evaluate YAML condition.

    Supported forms:
        '{matrix[key]} == "string"'
        '{matrix[key]} != "string"'
        '"{matrix[key]}" == "string"'
        '"{matrix[key]}" != "string"'
    """
    # Conjunction
    if isinstance(raw_condition, list):
        for item_condition in raw_condition:
            e = eval_if(item_condition, matrix, gvars)
            if not e:
                return False
        return True
    elif raw_condition is None:
        return True

    check_string(raw_condition)
    equality = (raw_condition.find("==") > -1)
    inequality = (raw_condition.find("!=") > -1)
    if equality:
        args = raw_condition.split("==")
    elif inequality:
        args = raw_condition.split("!=")
    else:
        error("Unsupported condition: '%s'." % raw_condition)
    if len(args) != 2:
        error("Wrong number of arguments: '%s'." % raw_condition)
    a = eval_bashlike(args[0].strip().replace('"', ''), matrix, gvars)
    b = eval_bashlike(args[1].strip().replace('"', ''), matrix, gvars)
    if equality:
        return a == b
    else:
        return a != b


def get_list_dict_dockerfile_matrix_tags_args(json, debug):
    """Directly called by main on the result of load_spec().

       Get list of dicts containing the following keys:
       - "context": "…"
       - "dockerfile": "…/Dockerfile"
       - "path": "…/…/Dockerfile"
       - "matrix": […]
       - "tags": […]
       - "args": […]
       - "keywords": […]
       - "after_deploy_script": […]
    """
    # TODO later-on: fix (dockerfile / path) semantics
    res = []
    images = json['images']
    args1 = json['args'] if 'args' in json else {}
    gvars = json['vars'] if 'vars' in json else {}
    # = global vars, interpolated in:
    # - args
    # - build.args
    # - build.tags
    # - build.after_deploy_export
    for item in images:
        list_matrix = product_build_matrix(item['matrix'])
        if 'dockerfile' in item['build']:
            dfile = check_trim_relative_path(item['build']['dockerfile'])
        else:
            dfile = 'Dockerfile'
        context = check_trim_relative_path(item['build']['context'])
        path = '%s/%s' % (context, dfile)
        raw_tags = item['build']['tags']
        args2 = item['build']['args'] if 'args' in item['build'] else {}
        raw_args = merge_dict(args1, args2)
        if 'keywords' in item['build']:
            raw_keywords = item['build']['keywords']
        else:
            raw_keywords = []
        if 'after_deploy' in item['build']:
            raw_after_deploy = item['build']['after_deploy']
            # support both
            #   after_deploy: 'code'
            # and
            #   after_deploy:
            #     - 'code'
            # as well as
            #   after_deploy:
            #     - run: 'code'
            #       if: '{matrix[base]} == 4.07.1-flambda'
            # and regarding interpolation, we can add:
            #   after_deploy_export:
            #     variable_name: 'value-{matrix[coq]}'
            # to prepend the after_deploy_script with export commands
            if isinstance(raw_after_deploy, str):
                raw_after_deploy = [raw_after_deploy]
        else:
            raw_after_deploy = []
        if 'after_deploy_export' in item['build']:
            raw_after_deploy_export = item['build']['after_deploy_export']
            check_dict(raw_after_deploy_export)
        else:
            raw_after_deploy_export = {}
        for matrix in list_matrix:
            tags = []
            for tag_item in raw_tags:
                tag_template = tag_item['tag']
                tag_cond = tag_item['if'] if 'if' in tag_item else None
                if eval_if(tag_cond, matrix, gvars):
                    # otherwise skip the tag synonym
                    tag = eval_bashlike(tag_template, matrix,
                                        gvars)  # NOT defaults
                    tags.append(tag)
            defaults = {"build_date": get_build_date()}
            if 'commit_api' in item['build']:
                commit_api = item['build']['commit_api']
                defaults['commit'] = get_commit(commit_api)  # TODO: auth?
            args = {}
            for arg_key in raw_args:
                arg_template = raw_args[arg_key]
                args[arg_key] = eval_bashlike(arg_template, matrix,
                                              gvars, defaults)
            keywords = list(map(lambda k: eval_bashlike(k, matrix,
                                                        gvars, defaults),
                                raw_keywords))

            after_deploy_export = []
            # Note: This could be a map:
            for var in raw_after_deploy_export:
                check_string(var)
                var_template = raw_after_deploy_export[var]
                var_value = eval_bashlike(var_template, matrix,
                                          gvars, defaults)
                # TODO soon: think about quoting var_value
                after_deploy_export.append("export %s='%s'" % (var, var_value))

            if raw_after_deploy:
                after_deploy_script = after_deploy_export
            else:
                after_deploy_script = []

            for ad_item in raw_after_deploy:
                if isinstance(ad_item, str):
                    after_deploy_script.append(ad_item)  # no { } interpolation
                    # otherwise sth like ${BASH_VARIABLE} would raise an error
                else:
                    script_item = ad_item['run']
                    script_cond = ad_item['if'] if 'if' in ad_item else None
                    if eval_if(script_cond, matrix, gvars):
                        # otherwise skip the script item
                        after_deploy_script.append(script_item)
            newitem = {"context": context, "dockerfile": dfile,
                       "path": path,
                       "matrix": matrix, "tags": tags, "args": args,
                       "keywords": keywords,
                       "after_deploy_script": after_deploy_script}
            res.append(newitem)
    if debug:
        print_stderr('get_list_dict_dockerfile_matrix_tags_args():')
        dump(res)
    return res


def gitlab_build_params_pagination(page, per_page):
    """https://docs.gitlab.com/ce/api/README.html#pagination"""
    return {
        'page': str(page),
        'per_page': str(per_page)
    }


def hub_build_params_pagination(page, per_page):
    return {
        'page': str(page),
        'page_size': str(per_page)
    }


def hub_lambda_list(j):
    """https://registry.hub.docker.com/v2/repositories/library/debian/tags"""
    return list(map(lambda e: e['name'], j['results']))


def get_list_paginated(url, headers, params, lambda_list, max_per_sec=5):
    """Generic wrapper to handle GET requests with pagination.

    If the response is a JSON list, use lambda_list=(lambda l: l).

    REM: for https://registry.hub.docker.com/v2/repositories/_/_/tags,
    one could use the "next" field to guess the following page."""
    assert isinstance(max_per_sec, int)
    assert max_per_sec > 0
    assert max_per_sec <= 10
    per_page = 50  # max allowed (by gitlab.com & hub.docker.com): 100
    page = 0
    allj = []
    while True:
        page += 1
        if page % max_per_sec == 0:
            time.sleep(1.1)
        page_params = hub_build_params_pagination(page, per_page)
        all_params = merge_dict(params, page_params)
        print_stderr("GET %s\n  # page: %d" % (url, page))
        response = requests.get(url, headers=headers, params=all_params)
        if response.status_code == 404:
            j = []
        elif not response:
            error("Error!\nCode: %d\nText: %s"
                  % (response.status_code, response.text))
        else:
            j = lambda_list(response.json())
        check_list(j, text=response.text)
        if j:
            allj += j
        else:
            break
    return allj


def get_remote_tags(spec):
    repo = spec['docker_repo']
    check_string(repo)
    return get_list_paginated(
        'https://registry.hub.docker.com/v2/repositories/%s/tags' % repo,
        None, None, hub_lambda_list)


def get_gitlab_ci_tags(spec):
    if 'gitlab_ci_tags' not in spec:
        gitlab_ci_tags = []
    else:
        gitlab_ci_tags = spec['gitlab_ci_tags']
    check_list(gitlab_ci_tags)
    return gitlab_ci_tags


def yaml_safe_quote(text):
    return '"' + text.replace('"', '\\"') + '"'


def oneliner_str_of_list(json):
    check_list(json)
    return '[' + ", ".join(map(lambda s: yaml_safe_quote(s), json)) + ']'


def minimal_rebuild(build_tags, remote_tags):
    def pred(item):
        return not subset_list(item['tags'], remote_tags)
    return list(filter(pred, build_tags))


def to_rm(all_tags, remote_tags):
    return diff_list(remote_tags, all_tags)


def get_script_directory():
    """$(cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd) in Python."""
    return os.path.dirname(__file__)


def get_script_rel2_directory():
    """relative path that's equivalent to: relpath(dirname(__file__), ../..)"""
    keeper_dir = get_script_directory()
    keeper_rel_dir = os.path.relpath(
        keeper_dir, os.path.dirname(os.path.dirname(keeper_dir)))
    return check_trim_relative_path(keeper_rel_dir)


def mkdir_dirname(filename):
    """Python3 equivalent to 'mkdir -p $(dirname $filename)"'."""
    os.makedirs(os.path.dirname(filename), mode=0o755, exist_ok=True)


def fullpath(filename):
    """Get path of filename in output_directory/."""
    return os.path.join(output_directory, filename)


def write_json_artifact(j, basename):
    filename = fullpath(basename)
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        json.dump(j, f, indent=json_indent)


def write_text_artifact(text, basename):
    filename = fullpath(basename)
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        f.write(text)


def write_list_text_artifact(seq, basename):
    check_list(seq)
    write_text_artifact('\n'.join(seq) + '\n', basename)


def write_build_data_all(build_data_all):
    write_json_artifact(build_data_all, 'build_data_all.json')


def write_build_data_chosen(build_data):
    write_json_artifact(build_data, 'build_data_chosen.json')


def write_build_data_min(build_data_min):
    write_json_artifact(build_data_min, 'build_data_min.json')


def write_remote_tags(remote_tags):
    write_list_text_artifact(remote_tags, 'remote_tags.txt')


def write_gitlab_ci_tags(gitlab_ci_tags):
    check_list(gitlab_ci_tags)
    write_text_artifact(oneliner_str_of_list(gitlab_ci_tags),
                        'gitlab_ci_tags.txt')


def write_remote_tags_to_rm(remote_tags_to_rm):
    write_json_artifact(remote_tags_to_rm, 'remote_tags_to_rm.json')


def write_propagate(propagate_data):
    write_json_artifact(propagate_data, 'propagate.json')


def write_list_dockerfile(seq):
    """To be used on the value of get_list_dict_dockerfile_matrix_tags_args."""
    dockerfiles = uniqify(map(lambda e: e['path'], seq))
    write_list_text_artifact(dockerfiles, 'Dockerfiles.txt')


def write_docker_repo(spec):
    repo = spec['docker_repo'] + '\n'
    write_text_artifact(repo, 'docker_repo.txt')


def read_json_artifact(basename):
    filename = fullpath(basename)
    print_stderr("Reading '%s'..." % filename)
    with open(filename, 'r') as json_data:
        j = json.load(json_data)
    return j


def read_build_data_chosen():
    return read_json_artifact('build_data_chosen.json')


def read_propagate():
    return read_json_artifact('propagate.json')


def write_readme(base_url, build_data):
    """Read README.md and replace <!-- tags --> with a list of images

    with https://gitlab.com/foo/bar/blob/master/Dockerfile hyperlinks.
    """
    pattern = '<!-- tags -->'
    check_string(base_url)
    if base_url[-1] == '/':
        base_url = base_url[:-1]

    def readme_image(item):
        return '-	[`{tags}`]({url})'.format(
            tags=('`, `'.join(item['tags'])),
            url=('%s/blob/master/%s' % (base_url, item['path'])))

    print_stderr("Reading the template 'README.md'...")
    with open('README.md', 'r') as f:
        template = f.read()

    tags = ('# <a name="supported-tags"></a>'
            'Supported tags and respective `Dockerfile` links\n\n%s'
            % '\n'.join(map(readme_image, build_data)))

    readme = template.replace(pattern, tags)

    filename = fullpath('README.md')
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        f.write(readme)


def get_check_tags(seq):
    """To be used on the value of get_list_dict_dockerfile_matrix_tags_args."""
    res = []
    for e in seq:
        res.extend(e['tags'])
    if is_unique(res):
        print_stderr("OK: no duplicate tag found.")
    else:
        error("Error: there are some tags duplicates.")
    return res


def merge_data(l1, l2):
    """Append to l1 the elements of l2 that do not belong to l1."""
    extra = diff_list(l2, l1)
    return l1 + extra


def get_nightly_only(spec, debug):
    spec2 = copy.deepcopy(spec)
    images = spec2.pop('images')

    def nightly(item):
        return 'nightly' in item['build'] and item['build']['nightly']

    images2 = list(filter(nightly, images))
    spec2['images'] = images2
    return get_list_dict_dockerfile_matrix_tags_args(spec2, debug)


def print_list(title, seq):
    print_stderr(title + ':' + ''.join(map(lambda e: '\n- ' + e, seq)))


def get_file_only(build_data_all, dockerfiles):
    print_list('Specified Dockerfiles', dockerfiles)

    # TODO later-on: fix (dockerfile / path) semantics
    def matching(item):
        return item['path'] in dockerfiles

    return list(filter(matching, build_data_all))


def get_tag_only(build_data_all, tags):
    print_list('Specified tags', tags)

    def matching(item):
        return meet_list(item['tags'], tags)

    return list(filter(matching, build_data_all))


def get_keyword_only(build_data_all, keywords):
    print_list('Specified keywords', keywords)

    def matching(item):
        return meet_list(item['keywords'], keywords)

    return list(filter(matching, build_data_all))


def get_files_list(items_filename):
    with open(items_filename, 'r') as fh:
        dockerfiles = [item.strip() for item in fh.readlines()]
    return dockerfiles


def get_tags_list(items_filename):
    with open(items_filename, 'r') as fh:
        tags = [item.strip() for item in fh.readlines()]
    return tags


def get_keywords_list(items_filename):
    with open(items_filename, 'r') as fh:
        keywords = [item.strip() for item in fh.readlines()]
    return keywords


def check_output_mode(mode):
    match mode:
        case 'nil':  # can only be used in 'images.yml'.propagate.strategy
            return
        case 'minimal':
            return
        case 'nightly':
            return
        case 'rebuild-keyword':
            return
        case 'rebuild-all':
            return
        case _:
            error("Error: invalid output value 'mode: %s'." % mode)


def check_manual_mode(mode):
    match mode:
        case 'minimal':
            return
        case 'nightly':
            return
        case 'rebuild-keyword':
            return
        case 'rebuild-all':
            return
        case _:
            error("Error: invalid manual value 'mode: %s'." % mode)


def get_propagate_strategy(spec, build_data_chosen,
                           triggered, manual_propagate):
    """Get propagate_strategy from images.yml, build_data_chosen, --propagate

    Regarding --propagate: can be specified by means of HEAD's commit message:
    git commit --allow-empty -m "…" -m "docker-keeper: nightly; propagate: ()"

    'images.yml'.'propagate' Syntax: sequence of:
      when: 'nightly' | 'rebuild-all' | 'forall' | 'exists'
      # when OPTIONAL for last sequence element
      expr:   # (forall/exisgts) 's,t'-list, interp({matrix},{tags},{keywords})
      subset: # (forall/exists) 's,t'-list, interpolation, expr subset of this
      mode: 'nil' | 'minimal' | 'nightly' | 'rebuild-keyword' | 'rebuild-all'
      item:   # (rebuild-keyword) concat; 's,t'-list; interpolation; uniqify

    'images.yml'.'propagate' Full example:
    propagate:
      random-slug:
        api_token_env_var: 'VAR_NAME'
        gitlab_domain: 'gitlab.com'
        gitlab_project: '42'
        strategy:
          # the first that matches (unless manual --propagate)
          # current limitation: triggers only 1 mode in child docker-keeper(§)
          - # when MANDATORY because not the last rule
            when: 'nightly' # this is the 1st possible (arg-free) input mode
            mode: 'nightly' # (§)so this cannot be a list
          - when: 'rebuild-all' # this is the 2d possible (arg-free) input mode
            mode: 'rebuild-all' # (§)so this cannot be a list
          - when: 'forall' # forall built image, the property holds
            expr: '{matrix[coq][//pl/.][%.*]}' # string or 's,t' list
            subset: '8.4,8.5'                  # is a subset of {8.4, 8.5}
            mode: 'nil'                        # do not propagate then
            # no explicit neg, but eval order + previous steps -> implicit neg
          - when: 'forall'
            expr: '{matrix[coq]}'
            subset: 'dev'
            # trigger a 'rebuild-keyword: dev'
            mode: 'rebuild-keyword' # (§)so this cannot be a list
            item: 'dev'             # string or 's,t' list; uniqify
          - # when OPTIONAL for last rule
            mode: 'minimal'
      mathcomp:
        api_token_env_var: 'VAR_NAME'
        gitlab_domain: 'gitlab.inria.fr'
        gitlab_project: '40'
        strategy:
          - when: 'rebuild-all'
            mode: 'rebuild-all'
          - when: 'forall'
            expr: '{matrix[coq][//pl/.][%.*]}'
            subset: '8.4,8.5'
            mode: 'nil'
          - # when OPTIONAL for last rule
            mode: 'rebuild-keyword'      # trigger a 'rebuild-keyword: s,t'
            item: '{keywords[/#/,][#,]}' # concat; 's,t' list; interp; uniqify
      mathcomp-dev:
        api_token_env_var: 'VAR_NAME'
        gitlab_domain: 'gitlab.inria.fr'
        gitlab_project: '41'
        strategy:
          - when: 'rebuild-all'
            mode: 'minimal'
          - when: 'forall'
            expr: '{matrix[coq]}'
            subset: 'dev'
            mode: 'nightly'
          - when: 'exists' # there exists a built image s.t. the property holds
            expr: '{matrix[coq][//pl/.][%.*]}' # string or 's,t' list
            subset: '8.19,8.20,dev'            # is a subset of {8.19,8.20,dev}
            mode: 'minimal'
          - # when OPTIONAL for last rule
            mode: 'nil'"""
    prop = spec['propagate'] if 'propagate' in spec else {}
    res_prop = {}

    at_least_one_manual = bool(manual_propagate)

    for slug in prop:
        prop1 = prop[slug]
        res_prop1 = {}

        api_token_env_var = prop1.pop('api_token_env_var')
        if not re.match(r'^[a-zA-Z_]+[a-zA-Z0-9_]*$', api_token_env_var):
            error("Error: invalid api_token_env_var for %s (was given '%s')."
                  % (slug, api_token_env_var))
        res_prop1['api_token_env_var'] = api_token_env_var
        gitlab_domain = prop1.pop('gitlab_domain')
        check_domain(gitlab_domain)
        res_prop1['gitlab_domain'] = gitlab_domain
        res_prop1['gitlab_project'] = prop1.pop('gitlab_project')

        strat = prop1.pop('strategy')
        check_no_fields(slug, prop1)
        check_list(strat)
        # check that each elt (except maybe the last one) has a 'when' property
        strat_drop1 = strat[:-1]
        for elt in strat_drop1:
            if 'when' not in elt:
                error("Error: propagate: %s: strategy: 'when' is mandatory %s."
                      % (slug, "(except for last list element)"))
        # 1a. manual strategy
        if slug in manual_propagate:
            res_prop1['strategy'] = manual_propagate.pop(slug)
            res_prop[slug] = res_prop1
            continue
        else:
            if at_least_one_manual:
                # disable automatic strategy; will try other (manual) slugs
                continue

        # 1b. otherwise, automatic strategy
        res_strat = {}
        # detect the first strategy elt that matches the 'when' property
        # and retrieve the output 'mode' (and interpolated 'item') in res_strat
        for elt in strat:
            if 'when' in elt:
                when = elt.pop('when')
                match when:
                    case 'nightly':
                        if 'nightly' in triggered and triggered['nightly']:
                            # BEGIN idem1
                            res_strat['mode'] = elt.pop('mode')
                            if res_strat['mode'] == 'rebuild-keyword':
                                raw_item = elt.pop('item')
                                res_strat['item'] = \
                                    uniq_cat_eval_propagate(raw_item,
                                                            build_data_chosen)
                            else:
                                check_output_mode(res_strat['mode'])
                            check_no_fields('strategy', elt)
                            break
                            # END idem1
                    case 'rebuild-all':
                        if 'rebuild_all' in triggered \
                           and triggered['rebuild_all']:
                            # BEGIN idem2
                            res_strat['mode'] = elt.pop('mode')
                            if res_strat['mode'] == 'rebuild-keyword':
                                raw_item = elt.pop('item')
                                res_strat['item'] = \
                                    uniq_cat_eval_propagate(raw_item,
                                                            build_data_chosen)
                            else:
                                check_output_mode(res_strat['mode'])
                            check_no_fields('strategy', elt)
                            break
                            # END idem2
                    case 'forall':
                        acc = True
                        expr = elt.pop('expr')
                        subset = elt.pop('subset')
                        for build in build_data_chosen:
                            e_expr = eval_propagate(expr, build)
                            e_subset = eval_propagate(subset, build)
                            if not subset_comma_list(e_expr, e_subset):
                                acc = False
                                break
                        if acc:
                            # BEGIN idem3
                            res_strat['mode'] = elt.pop('mode')
                            if res_strat['mode'] == 'rebuild-keyword':
                                raw_item = elt.pop('item')
                                res_strat['item'] = \
                                    uniq_cat_eval_propagate(raw_item,
                                                            build_data_chosen)
                            else:
                                check_output_mode(res_strat['mode'])
                            check_no_fields('strategy', elt)
                            break
                            # END idem3
                        else:
                            ignore_fields(elt, ['mode', 'item'])
                            check_no_fields('strategy', elt)
                    case 'exists':
                        acc = False  # dual
                        expr = elt.pop('expr')
                        subset = elt.pop('subset')
                        for build in build_data_chosen:
                            e_expr = eval_propagate(expr, build)
                            e_subset = eval_propagate(subset, build)
                            if subset_comma_list(e_expr, e_subset):  # dual
                                acc = True  # dual
                                break
                        if acc:
                            # BEGIN idem4
                            res_strat['mode'] = elt.pop('mode')
                            if res_strat['mode'] == 'rebuild-keyword':
                                raw_item = elt.pop('item')
                                res_strat['item'] = \
                                    uniq_cat_eval_propagate(raw_item,
                                                            build_data_chosen)
                            else:
                                check_output_mode(res_strat['mode'])
                            check_no_fields('strategy', elt)
                            break
                            # END idem4
                        else:
                            ignore_fields(elt, ['mode', 'item'])
                            check_no_fields('strategy', elt)
                    case _:
                        error("Error: propagate: %s: strategy: %s 'when: %s'"
                              % (slug, 'unexpected', elt['when']))
            else:
                # BEGIN idem5
                res_strat['mode'] = elt.pop('mode')
                if res_strat['mode'] == 'rebuild-keyword':
                    raw_item = elt.pop('item')
                    res_strat['item'] = \
                        uniq_cat_eval_propagate(raw_item,
                                                build_data_chosen)
                else:
                    check_output_mode(res_strat['mode'])
                check_no_fields('strategy', elt)
                break
                # END idem5

        res_prop1['strategy'] = res_strat
        if 'mode' in res_strat and res_strat['mode'] != 'nil':
            res_prop[slug] = res_prop1

    # check that all manually-specified propagate slug belonged in the strategy
    if at_least_one_manual:
        check_no_fields('manual_propagate', manual_propagate)
    return res_prop


def get_version():
    with open(os.path.join(get_script_directory(), 'VERSION'), 'r') as f:
        version = f.read().strip()
    return version


def get_upstream_version():
    url = ('https://gitlab.com/api/v4/projects/%s/repository/files/VERSION'
           % naive_url_encode(upstream_project))

    def lambda_query_content(response):
        return (base64.b64decode(response.json()['content'])
                .decode('UTF-8').rstrip())

    return get_url(url, None, {"ref": "master"}, lambda_query_content)


def equalize_args(record):
    """{"VAR1": "value1", "VAR2": "value2"} → ['VAR1=value1', 'VAR2=value2']"""
    res = []
    for key in record:
        res.append("%s=%s" % (key, record[key]))
    return res


def indent_script(list_after_deploy, indent_level, start=False):
    check_list(list_after_deploy)
    if list_after_deploy:
        indent = " " * indent_level
        if start:
            return indent + ('\n' + indent).join(list_after_deploy)
        else:
            return ('\n' + indent).join(list_after_deploy)
    else:
        return ""


def escape_single_quotes(script):
    return script.replace("'", "'\\''")


def generate_config(docker_repo, gitlab_ci_tags, propagate_data):
    data = read_build_data_chosen()

    if gitlab_ci_tags:
        str_gitlab_ci_tags = """default:
  tags: {string}
""".format(string=str(gitlab_ci_tags))
    else:
        str_gitlab_ci_tags = ''

    if not data:
        yamlstr_init = """---
# GitLab CI config automatically generated by docker-keeper; do not edit.
# yamllint disable rule:line-length rule:empty-lines

{var_gitlab_ci_tags}
stages:
  - build
  - propagate

noop:
  stage: build
  image: alpine:latest
  variables:
    GIT_STRATEGY: none
  script:
    - echo "No image to rebuild."
  only:
    - master

.curl-propagate:
  stage: propagate
  only:
    - master
  variables:
  image: alpine:latest
  before_script:
    - echo $0
    - apk add --no-cache bash
    - /usr/bin/env bash --version
    - apk add --no-cache curl
    - curl --version
    - pwd

{var_jobs}"""

    else:
        yamlstr_init = """---
# GitLab CI config automatically generated by docker-keeper; do not edit.
# yamllint disable rule:line-length rule:empty-lines

{var_gitlab_ci_tags}
stages:
  - deploy
  - remove
  - propagate

# Changes below (or jobs extending .docker-deploy) should be carefully
# reviewed to avoid leaks of HUB_TOKEN
.docker-deploy:
  stage: deploy
  only:
    - master
  variables:
    HUB_REPO: "{var_hub_repo}"
    # HUB_USER: # protected variable
    # HUB_TOKEN: # protected variable
    # FOO_TOKEN: # other, user-defined tokens for after_deploy_script
  image: docker:latest
  services:
    - docker:dind
  before_script:
    - cat /proc/cpuinfo /proc/meminfo
    - echo $0
    - apk add --no-cache bash
    - /usr/bin/env bash --version
    - apk add --no-cache curl
    - curl --version
    - pwd

.curl-propagate:
  stage: propagate
  only:
    - master
  variables:
  image: alpine:latest
  before_script:
    - echo $0
    - apk add --no-cache bash
    - /usr/bin/env bash --version
    - apk add --no-cache curl
    - curl --version
    - pwd

{var_jobs}"""

    # See https://gitlab.com/erikmd/docker-keeper-template
    # /-/blob/master/.gitlab-ci.yml#L5
    keeper_subtree = os.getenv("KEEPER_SUBTREE")
    if keeper_subtree:
        print_stderr("Info: non-empty env-var KEEPER_SUBTREE=\"%s\""
                     % keeper_subtree)
    else:
        keeper_subtree = get_script_rel2_directory()
        print_stderr("Info: call get_script_rel2_directory()=\"%s\""
                     % keeper_subtree)

    yamlstr_jobs = ''
    job_id = 0
    for item in data:
        job_id += 1
        yamlstr_jobs += """
deploy_{var_job_id}_{var_some_real_tag}:
  extends: .docker-deploy
  script: |
    /usr/bin/env bash -e -c '
      echo $0
      . "{var_keeper_subtree}/gitlab_functions.sh"
      dk_login
      dk_build "{var_context}" "{var_dockerfile}" "{var_one_tag}" {vars_args}
      dk_push "{var_hub_repo}" "{var_one_tag}" {vars_tags}
      dk_logout
      {var_after_deploy}' bash
""".format(var_context=item['context'],
           var_dockerfile=item['dockerfile'],
           vars_args=('"%s"' % '" "'.join(equalize_args(item['args']))),
           vars_tags=('"%s"' % '" "'.join(item['tags'])),
           var_keeper_subtree=keeper_subtree,
           var_hub_repo=docker_repo,
           var_one_tag=("image_%d" % job_id),
           var_job_id=job_id,
           var_some_real_tag=first_shortest_tag(item['tags']),
           var_after_deploy=escape_single_quotes(
               indent_script(item['after_deploy_script'], 6)))

    curl_propagate = []
    for slug in propagate_data:
        prop = propagate_data[slug]
        strat = prop['strategy']
        if 'item' in strat:
            check_list(strat['item'])
            item = ','.join(strat['item'])
        else:
            item = ''
        next_curl = ('dk_curl "{var_slug}" "{var_tok}" "{var_dom}" "{var_prj}"'
                     + ' "{var_mod}" "{var_it}"').format(
                         var_slug=slug,
                         var_tok='$' + prop['api_token_env_var'],
                         var_dom=prop['gitlab_domain'],
                         var_prj=prop['gitlab_project'],
                         var_mod=prop['strategy']['mode'],
                         var_it=item)
        curl_propagate.append(next_curl)
    if propagate_data:
        yamlstr_jobs += """
propagate:
  extends: .curl-propagate
  script: |
    /usr/bin/env bash -e -c '
      echo $0
      . "{var_keeper_subtree}/gitlab_functions.sh"
      {var_curl_propagate}' bash
""".format(var_keeper_subtree=keeper_subtree,
           var_curl_propagate=indent_script(curl_propagate, 6))

    return yamlstr_init.format(var_gitlab_ci_tags=str_gitlab_ci_tags,
                               var_hub_repo=docker_repo,
                               var_jobs=yamlstr_jobs)


def main_generate_config(upstream_version):
    spec = load_spec()  # could be avoided by writing yet another .json…
    propagate_data = read_propagate()
    print(generate_config(spec['docker_repo'],
                          get_gitlab_ci_tags(spec), propagate_data))


def main_write_artifacts(upstream_version, minimal,  # <- input ignored
                         rebuild_files, rebuild_tags, rebuild_keywords,
                         # ^- deprecated
                         rebuild_file, rebuild_tag, rebuild_keyword,
                         # ^- supports comma-separated lists
                         debug, nightly, propagate, rebuild_all):
    spec = load_spec()
    build_data_all = get_list_dict_dockerfile_matrix_tags_args(spec, debug)
    all_tags = get_check_tags(build_data_all)
    remote_tags = get_remote_tags(spec)
    build_data_min = minimal_rebuild(build_data_all, remote_tags)
    remote_tags_to_rm = to_rm(all_tags, remote_tags)

    res_nightly = []
    if nightly:
        res_nightly = get_nightly_only(spec, debug)
        # reminder: merge_data(build_data_min, res_nightly), and likewise below

    # BEGIN deprecated
    res_rebuild_files = []
    if rebuild_files:
        for fil in rebuild_files:
            res_rebuild_files += get_files_list(fil)

    res_rebuild_tags = []
    if rebuild_tags:
        for fil in rebuild_tags:
            res_rebuild_tags += get_tags_list(fil)

    res_rebuild_keywords = []
    if rebuild_keywords:
        for fil in rebuild_keywords:
            res_rebuild_keywords += get_keywords_list(fil)
    # END deprecated

    # BEGIN on the edge
    items = uniqify(flat_map_trim_comma_split(rebuild_file)
                    + res_rebuild_files)
    res_rebuild_file = get_file_only(build_data_all, items)

    items = uniqify_tags(flat_map_trim_comma_split(rebuild_tag)
                         + res_rebuild_tags)
    res_rebuild_tag = get_tag_only(build_data_all, items)

    items = uniqify_tags(flat_map_trim_comma_split(rebuild_keyword)
                         + res_rebuild_keywords)
    res_rebuild_keyword = get_keyword_only(build_data_all, items)
    # END on the edge

    if rebuild_all:
        build_data_tags = build_data_all
    else:
        build_data_tags = build_data_min
        build_data_tags = merge_data(build_data_tags, res_nightly)
        build_data_tags = merge_data(build_data_tags, res_rebuild_file)
        build_data_tags = merge_data(build_data_tags, res_rebuild_tag)
        build_data_tags = merge_data(build_data_tags, res_rebuild_keyword)

    # Pre-processing
    # --propagate=SLUG: minimal
    # --propagate=SLUG: nightly
    # --propagate=SLUG: rebuild-all
    # --propagate=SLUG: rebuild-keyword: KW1,KW2
    manual_propagate = {}
    if propagate:
        print_stderr("Set manual propagation using commit-msg, gitlab-var"
                     + ", or CLI--propagate.")
        for elt in propagate:
            if elt == '()':
                continue
            msed = \
                re.match(r'^([A-Za-z0-9_-]+): *([a-z-]+)(?:[:] *([\w._-]+))?$',
                         elt)
            if not msed:
                error("Error: incorrect syntax '--propagate=%s'." % elt)
            slug, command, item = msed.groups()
            check_manual_mode(command)
            if command == 'rebuild-keyword':
                if not item:
                    error("Error: '--propagate=_: rebuild-keyword:' "
                          + "missing item")
            else:
                if item:
                    error("Error: '--propagate=_: %s': "
                          + "unexpected item" % command)
            res_elt = {}
            res_elt['mode'] = command
            if item:  # here, a string or comma-separated list
                res_elt['item'] = uniqify_tags(trim_comma_split(item))
            manual_propagate[slug] = res_elt
        # if debug:
        print_stderr('Specified manual_propagate:')
        dump(manual_propagate)
    else:
        print_stderr("Applying propagate strategy automatically from '%s'..."
                     % images_filename)

    # value for get_propagate_strategy: detect 'nightly'/'rebuild-all' events
    triggered = {}
    if rebuild_all:
        triggered['rebuild_all'] = True
    elif nightly:
        triggered['nightly'] = True
    if debug and triggered:
        print_stderr('triggered:')
        dump(triggered)

    # Processing CLI
    # --propagate=()
    # --propagate=SLUG: minimal
    # --propagate=SLUG: nightly
    # --propagate=SLUG: rebuild-all
    # --propagate=SLUG: rebuild-keyword: KW1,KW2
    propagate_data = {}

    if propagate:
        # manual option - `if manual_propagate:` would be wrong b/o '()'.
        if '()' in propagate:
            print_stderr("Got '--propagate=()': disable propagation.")
        else:
            propagate_data = get_propagate_strategy(spec, build_data_tags,
                                                    triggered,
                                                    manual_propagate)
    else:
        # automatic option
        propagate_data = get_propagate_strategy(spec, build_data_tags,
                                                triggered, {})

    if debug:
        print_stderr('propagate_data:')
        dump(propagate_data)

    write_propagate(propagate_data)
    write_build_data_chosen(build_data_tags)
    write_build_data_all(build_data_all)
    write_build_data_min(build_data_min)
    write_remote_tags(remote_tags)
    write_remote_tags_to_rm(remote_tags_to_rm)
    write_list_dockerfile(build_data_all)
    write_readme(spec['base_url'], build_data_all)
    write_docker_repo(spec)
    write_gitlab_ci_tags(get_gitlab_ci_tags(spec))


def main(argv):
    parser = argparse.ArgumentParser(
        prog=prog, description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # --version
    parser.add_argument('--version', action='version',
                        version=(get_version()))
    # --upstream-version
    help_upstream_version = """
    show program's upstream version from %s and exit""" % upstream_url
    parser.add_argument('--upstream-version', action='store_true',
                        help=help_upstream_version)
    subparsers = parser.add_subparsers(title='subcommands', help=None)

    # generate-config
    help_generate_config = """
    Print a GitLab CI YAML config to standard output.
    This requires files: {generated/build_data_chosen.json,
    generated/remote_tags_to_rm.json}"""
    parser_generate_config = \
        subparsers.add_parser('generate-config',
                              # no parents parser
                              help=help_generate_config,
                              description=help_generate_config)
    parser_generate_config.set_defaults(func=main_generate_config)

    # write-artifacts
    help_write_artifacts = """
    Generate artifacts in the '%s' directory.
    This requires having file '%s' in the current working directory.
    """ % (output_directory, images_filename)
    parser_write_artifacts = \
        subparsers.add_parser('write-artifacts',
                              # no parents parser
                              help=help_write_artifacts,
                              description=help_write_artifacts)
    several = ' (can be supplied several times)'
    # --debug
    help_debug = """
    help debugging by printing more info (especially regarding argparse)"""
    parser_write_artifacts.add_argument('--debug', action='store_true',
                                        help=help_debug)
    # --minimal
    help_minimal = """
    default option, can be omitted, kept for backward compatibility"""
    parser_write_artifacts.add_argument('--minimal', action='store_true',
                                        help=help_minimal)
    # --nightly
    help_nightly = "trigger builds that have the 'nightly: true' flag"
    parser_write_artifacts.add_argument('--nightly', action='store_true',
                                        help=help_nightly)
    # --rebuild-all
    help_rebuild_all = "rebuild all images"
    parser_write_artifacts.add_argument('--rebuild-all', action='store_true',
                                        help=help_rebuild_all)
    # --rebuild-files FILE
    help_rebuild_files = """
    (deprecated) rebuild images with Dockerfile mentioned in FILE"""
    parser_write_artifacts.add_argument('--rebuild-files', action='append',
                                        metavar='FILE',
                                        help=help_rebuild_files + several)
    # --rebuild-tags FILE
    help_rebuild_tags = """
    (deprecated) rebuild images with tag mentioned in FILE"""
    parser_write_artifacts.add_argument('--rebuild-tags', action='append',
                                        metavar='FILE',
                                        help=help_rebuild_tags + several)
    # --rebuild-keywords FILE
    help_rebuild_keywords = """
    (deprecated) rebuild images with keyword mentioned in FILE"""
    parser_write_artifacts.add_argument('--rebuild-keywords', action='append',
                                        metavar='FILE',
                                        help=help_rebuild_keywords + several)
    # --rebuild-file NAME1,NAME2
    help_rebuild_file = """
    rebuild images with Dockerfile mentioned in CLI comma-separated list"""
    parser_write_artifacts.add_argument('--rebuild-file', action='append',
                                        metavar='NAME1,NAME2',
                                        help=help_rebuild_file + several)
    # --rebuild-tag TAG1,TAG2
    help_rebuild_tag = """
    rebuild images with tag mentioned in CLI comma-separated list"""
    parser_write_artifacts.add_argument('--rebuild-tag', action='append',
                                        metavar='TAG1,TAG2',
                                        help=help_rebuild_tag + several)
    # --rebuild-keyword KW1,KW2
    help_rebuild_keyword = """
    rebuild images with keyword mentioned in CLI comma-separated list"""
    parser_write_artifacts.add_argument('--rebuild-keyword', action='append',
                                        metavar='KW1,KW2',
                                        help=help_rebuild_keyword + several)
    # --propagate=()
    # --propagate=SLUG: minimal
    # --propagate=SLUG: nightly
    # --propagate=SLUG: rebuild-all
    # --propagate=SLUG: rebuild-keyword: KW1,KW2
    help_propagate = """
    manually specify to propagate 'minimal', 'nightly', 'rebuild-all',
    or 'rebuild-keyword: KW1,KW2' commands
    to children docker-keeper repositories;
    note that you can use '--propagate=()' to disable propagation fully,
    independently of the other occurrences of this option;
    if there is no occurrence of this option (in CLI
    nor in HEAD's commit message), docker-keeper will apply the
    propagate strategy defined in the %s file""" % images_filename
    parser_write_artifacts.add_argument('--propagate', action='append',
                                        metavar="'CHILD-REPO: COMMAND'",
                                        help=help_propagate + several)
    parser_write_artifacts.set_defaults(func=main_write_artifacts)

    # main
    args = vars(parser.parse_args(argv))
    if 'debug' in args and args['debug']:
        print_stderr('argparse:')
        print_stderr(args)
    if args["upstream_version"]:
        print(get_upstream_version())
    elif ("func" in args):
        func = args.pop("func")
        func(**args)
    else:
        parser.print_help()


###############################################################################
# Test suite, cf. <https://docs.python-guide.org/writing/tests/>
# $ pip3 install pytest
# $ py.test bash_formatter.py

def test_get_commit():
    github = {"fetcher": "github", "repo": "coq/coq", "branch": "v8.0"}
    github_expected = "f7777da84893a182f566667426d13dd43f2ee45a"
    github_actual = get_commit(github)
    assert github_actual == github_expected
    gitlab = {"fetcher": "gitlab", "repo": "coq/coq", "branch": "v8.0"}
    gitlab_expected = "f7777da84893a182f566667426d13dd43f2ee45a"
    gitlab_actual = get_commit(gitlab)
    assert gitlab_actual == gitlab_expected


def shouldfail(lam):
    try:
        res = lam()
        print_stderr("Wrong outcome: '%s'" % res)
        assert False
    except Error:
        print_stderr('OK')


def test_check_trim_relative_path():
    assert check_trim_relative_path('.') == '.'
    assert check_trim_relative_path('./foo/bar') == 'foo/bar'
    assert check_trim_relative_path('bar/baz') == 'bar/baz'
    shouldfail(lambda: check_trim_relative_path('/etc'))


def test_get_script_rel2_directory():
    dir2 = get_script_rel2_directory()
    assert '/' in dir2
    assert os.path.basename(dir2) == 'docker-keeper'


def test_eval_if():
    matrix1 = {"base": "latest", "coq": "dev"}
    matrix2 = {"base": "4.09.0-flambda", "coq": "8.7.2"}
    gvars = {"coq_dev": "dev"}
    assert eval_if('{matrix[base]}=="latest"', matrix1, gvars)
    assert eval_if('{matrix[base]} == "latest"', matrix1, gvars)
    assert eval_if(' "{matrix[base]}" == "latest"', matrix1, gvars)
    assert eval_if('{matrix[base]}!="latest"', matrix2, gvars)
    assert eval_if('{matrix[base]} != "latest"', matrix2, gvars)
    assert eval_if(' "{matrix[base]}" != "latest"', matrix2, gvars)
    assert eval_if('{matrix[coq]} == {vars[coq_dev]}', matrix1, gvars)
    assert eval_if('{matrix[coq]} != {vars[coq_dev]}', matrix2, gvars)


def test_eval_bashlike():
    matrix = {"base": "4.09.0-flambda", "coq": "8.19.0"}
    gvars = {"coq_latest": "8.19.1"}
    template0 = '{matrix[coq]}-ocaml-{matrix[base]}'
    template1 = '{vars[coq_latest]}-ocaml-{matrix[base]}'
    template20 = '{matrix[coq][%.*]}-ocaml-{matrix[base][%.*-*]}-flambda'
    template21 = '{vars[coq_latest][%.*]}-ocaml-{matrix[base][%.*-*]}-flambda'
    assert eval_bashlike(template0, matrix,
                         gvars, None) == '8.19.0-ocaml-4.09.0-flambda'
    assert eval_bashlike(template1, matrix,
                         gvars, None) == '8.19.1-ocaml-4.09.0-flambda'
    assert eval_bashlike(template20, matrix,
                         gvars, None) == '8.19-ocaml-4.09-flambda'
    assert eval_bashlike(template21, matrix,
                         gvars, None) == '8.19-ocaml-4.09-flambda'


def test_is_unique():
    s = [1, 2, 4, 0, 4]
    assert not is_unique(s)
    s = uniqify(s)
    assert is_unique(s)


def test_uniqify():
    assert uniqify([1, 2, 4, 0, 4]) == [0, 1, 2, 4]


def test_merge_dict():
    foo = {'a': 1, 'c': 2}
    bar = {'b': 3, 'c': 4}
    foobar = merge_dict(foo, bar)
    assert foobar == {'a': 1, 'b': 3, 'c': 4}


def test_diff_list():
    l1 = [1, 2, 4, 2, 5, 4]
    l2 = [3, 1, 2]
    assert diff_list(l1, l2) == [4, 5, 4]


def test_subset_list():
    l2 = [2, 3]
    l1 = [2]
    l0 = [3, 4, 5]
    l3 = [2, 3, 5]
    assert subset_list(l2, l3)
    assert not subset_list(l2, l1)
    assert not subset_list(l2, l0)


def test_equalize_args():
    assert (equalize_args({"VAR1": "value1", "VAR2": "value2"}) ==
            ['VAR1=value1', 'VAR2=value2'])


def test_merge_data():
    l1 = [{"i": 1, "s": "a"}, {"i": 2, "s": "b"}, {"i": 1, "s": "a"}]
    l2 = [{"i": 2, "s": "b"}, {"i": 2, "s": "b"}, {"i": 3, "s": "c"}]
    res1 = merge_data(l1, l2)
    assert res1 == [{"i": 1, "s": "a"}, {"i": 2, "s": "b"}, {"i": 1, "s": "a"},
                    {"i": 3, "s": "c"}]
    res2 = merge_data(l2, l1)
    assert res2 == [{"i": 2, "s": "b"}, {"i": 2, "s": "b"}, {"i": 3, "s": "c"},
                    {"i": 1, "s": "a"}, {"i": 1, "s": "a"}]


def test_meet_list():
    assert not meet_list([1, 2], [])
    assert not meet_list([], [2, 3])
    assert not meet_list([1, 2], [3])
    assert meet_list([1, 2], [2, 3])


def test_first_shortest_tag():
    assert first_shortest_tag(['BB', 'AA', 'z', 'y']) == 'y'


def test_indent_script():
    assert indent_script(['echo ok', 'echo "The End"'], 6, True) == \
        '      echo ok\n      echo "The End"'
    assert indent_script(['echo ok', 'echo "The End"'], 6) == \
        'echo ok\n      echo "The End"'


def test_trim_comma_split():
    assert trim_comma_split('') == []
    assert flat_map_trim_comma_split(None) == []
    assert trim_comma_split(',dev,dev-native,dev,') == \
        ['dev', 'dev-native', 'dev']
    assert sorted(flat_map_trim_comma_split(['dev', '8.19,8.20,',
                                             'dev,dev-native'])) == \
        sorted(['8.19', '8.20', 'dev', 'dev', 'dev-native'])
    assert uniqify_tags(trim_comma_split('dev')) == ['dev']
    assert uniqify_tags(trim_comma_split('dev,dev,')) == ['dev']


if __name__ == "__main__":
    main(sys.argv[1:])
