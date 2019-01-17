from __future__ import print_function, absolute_import, division, unicode_literals

from argparse import ArgumentParser
from datetime import datetime as dtime, timedelta as tdel
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

_default_reinit_pattern = 'Reinit-' + _wrf_date_fmt


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
    description = 'Bulk convert WRF files to ARL format'
    if parser is None:
        parser = ArgumentParser(description=description)
        i_am_main = True
    else:
        parser.description = description
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


############################
# For linking reinit files #
############################

def _datefmt_to_re(fmt):
    replacements = {'%Y': r'\d\d\d\d', '%m': r'\d\d', '%d': r'\d\d', '%H': r'\d\d', '%M': r'\d\d', '%S': r'\d\d'}
    for old, new in replacements.items():
        fmt = fmt.replace(old, new)

    if '%' in fmt:
        raise ValueError('Some time formats not understood. End result was {}'.format(fmt))
    else:
        return fmt


def drive_link_reinit(spinup_time, output_dir, input_dir='.', reinit_pattern=_default_reinit_pattern,
                      arl_pattern=_default_output_pattern):
    # Don't care what domain it is, just link it
    arl_date_pattern = re.sub(r'\{.*?domain.*?\}', '', arl_pattern)
    arl_re_pattern = _datefmt_to_re(arl_date_pattern)

    possible_reinit_dirs = os.listdir(input_dir)
    for d in possible_reinit_dirs:
        try:
            reinit_datetime = dtime.strptime(d, reinit_pattern)
        except ValueError:
            # doesn't match the pattern given for the reinit directories, skip
            continue

        possible_arl_files = os.listdir(os.path.join(input_dir, d))
        for f in possible_arl_files:
            date_part = re.search(arl_re_pattern, f)
            if date_part is not None:
                arl_date = dtime.strptime(date_part.group(), arl_date_pattern)
                if arl_date - reinit_datetime > spinup_time:
                    arl_src = os.path.abspath(os.path.join(input_dir, d, f))
                    arl_dest = os.path.join(output_dir, f)
                    if os.path.islink(arl_dest):
                        os.remove(arl_dest)
                    os.symlink(arl_src, arl_dest)


def _parse_time_string_dhms(time_str):
    parts = {'days': re.compile(r'\d+(?=d)'),
             'hours': re.compile(r'\d+(?=h)'),
             'minutes': re.compile(r'\d+(?=m)'),
             'seconds': re.compile(r'\d+(?=s)')}

    durations = dict()
    for part, regex in parts.items():
        user_dur = regex.search(time_str)
        if user_dur is not None:
            durations[part] = int(user_dur.group())

    return tdel(**durations)


def setup_link_clargs(parser=None):
    description = 'Link files from multiple reinitialization directories into one'
    if parser is None:
        parser = ArgumentParser(description=description)
        i_am_main = True
    else:
        parser.description = description
        i_am_main = False

    parser.add_argument('spinup_time', type=_parse_time_string_dhms,
                        help='How long from the start of each reinitialization to treat as spinup and '
                             'not link. Give as NdNhNmNs, where the Ns are days, hours, minutes or '
                             'seconds. Any part may be omitted, e.g. "1d", "6h", or "1d6h" are all '
                             'valid values.')
    parser.add_argument('input_dir', default='.', nargs='?', help='The directory to find the Reinit subdirectories in.')
    parser.add_argument('-o', '--output-dir', default='.', help='Where to link the ARL files to')
    parser.add_argument('--reinit-pattern', default=_default_reinit_pattern,
                        help='The pattern to match reinitialization directories. Default is "%(default)s".')
    parser.add_argument('--arl-pattern', default=_default_output_pattern,
                        help='The pattern to match for ARL files. Default is "%(default)s".')

    parser.set_defaults(exec_fxn=drive_link_reinit)

    if i_am_main:
        return vars(parser.parse_args())


def link_main():
    args = setup_link_clargs()
    exec_fxn = args.pop('exec_fxn')
    exec_fxn(**args)


if __name__ == '__main__':
    main()
