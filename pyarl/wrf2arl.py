from __future__ import print_function, absolute_import, division, unicode_literals

from argparse import ArgumentParser
from datetime import datetime as dtime
from glob import glob
import re
import os
import shutil
import subprocess

from . import PyarlConfig, WRF2ARL, WRF2ARL_DIR


_wrf_domain_re = re.compile(r'(?<=d)\d{2}')
_wrf_date_re = re.compile(r'\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2}')
_wrf_date_fmt = '%Y-%m-%d_%H:%M:%S'

_default_output_pattern = '%Y%m%d.%Hz.wrf{domain:02d}'


def _mkdir_recursive(new_dir):
    dir_parts = new_dir.split(os.pathsep)
    for i in range(len(dir_parts)):
        sub_dir = os.path.join(dir_parts[:i+1])
        if not os.path.isdir(sub_dir):
            os.mkdir(sub_dir)


def _convert_wrf_file(wrf_file, wrfnc2arl_exe, variable_file, output_dir='.',
                      output_pattern=_default_output_pattern):

    wrf_base_filename = os.path.basename(wrf_file)
    wrf_datetime = dtime.strptime(_wrf_date_re.search(wrf_base_filename).group(), _wrf_date_fmt)
    domain = int(_wrf_domain_re.search(wrf_base_filename).group())
    output_file = output_pattern.format(domain=domain)
    output_file = wrf_datetime.strftime(output_file)
    output_file = os.path.join(output_dir, output_file)

    subprocess.check_call([wrfnc2arl_exe, '-P', variable_file, wrf_file])
    _mkdir_recursive(os.path.dirname(output_file))
    shutil.move('DATA_MASS.WRF', output_file)


def _globstr2restr(globstr):
    return globstr.replace('*', '.*').replace('?', '.')


def _build_wrf_file_list(file_pattern, recursive_search=False):
    if not recursive_search:
        return glob(file_pattern)

    file_list = []
    re_str = _globstr2restr(file_pattern)
    for dirpath, _, dirfiles in os.walk('.'):
        dirpath = dirpath.lstrip('./')
        for f in dirfiles:
            if re.match(re_str, f):
                file_list.append(os.path.join(dirpath, f))

    return file_list


def _get_variable_file(variable_file, wrf2arl_dir):
    if not os.path.isabs(variable_file) and not variable_file.startswith('.'):
        if wrf2arl_dir == '':
            raise RuntimeError('No wrf2arl directory specified in the config. To indicate a variable file in the '
                               'current directory, prefix the name with "./", e.g. "./var_sample".')
        variable_file = os.path.join(wrf2arl_dir, variable_file)

    if not os.path.isfile(variable_file):
        raise RuntimeError('Specified variable file ({}) does not exist'.format(variable_file))


def drive_wrfnc2arl(file_pattern, arl_variable_file, recursive=False, output_dir='.',
                    output_pattern=_default_output_pattern):

    config = PyarlConfig()
    wrf2arl_dir = config[WRF2ARL][WRF2ARL_DIR]
    if wrf2arl_dir == '':
        # if no directory given, maybe its on the PATH?
        wrf2arl_exe = 'wrfnc2arl'
    else:
        wrf2arl_exe = os.path.join(wrf2arl_dir, 'wrfnc2arl')

    arl_variable_file = _get_variable_file(arl_variable_file, wrf2arl_dir)
    wrf_files = _build_wrf_file_list(file_pattern, recursive_search=recursive)
    for f in wrf_files:
        _convert_wrf_file(f, wrf2arl_exe, arl_variable_file, output_dir=output_dir, output_pattern=output_pattern)


def setup_clargs(parser=None):
    if parser is None:
        parser = ArgumentParser(description='Bulk convert WRF files to ARL format')
        i_am_main = True
    else:
        i_am_main = False

    parser.add_argument('file_pattern', help='Convert files matching this pattern. Enclose in quotes to avoid '
                                             'expanding globs in the shell, e.g. %(prog)s "wrfout*".')
    parser.add_argument('arl_variable_file', help='Which variable file to use for converting WRF variables to ARL '
                                                  'variables. If given as an absolute path or a path starting with '
                                                  '"./" or "../", then the file pointed to by that path is used. If '
                                                  'given without a leading "./" or "../", then it will be looked for '
                                                  'in the wrf2arl directory.')
    parser.add_argument('-R', '--recursive', action='store_true',
                        help='Search for files matching the given pattern recursively in the current directory. '
                             'Output files will be stored in a directory tree under output_dir mimicing the directory '
                             'structure here.')
    parser.add_argument('-o', '--output-dir', default='.', help='The directory to store the output files in. Default '
                                                                'is the current directory.')
    parser.add_argument('-O', '--output-pattern', default=_default_output_pattern,
                        help='The naming pattern to use for output files. Python datetime formatting can be used to '
                             'specify how to include the date and its bracket formatting for the keyword "domain" '
                             'will be replaced with the WRF domain number. Default is "%(default)s".' )

    parser.set_defaults(exec_fxn=drive_wrfnc2arl)

    if i_am_main:
        return vars(parser.parse_args())


def main():
    args = setup_clargs()
    exec_func = args.pop('exec_fxn')
    exec_func(**args)


if __name__ == '__main__':
    main()
