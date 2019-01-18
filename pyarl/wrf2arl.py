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
    """
    Make a full directory path even if intemediate parts don't exist.

    Should behave equivalently to "mkdir -p" on Unix systems, not tested on Windows. Example::

        _mkdir_recursive('WRF/Run1/Data')

    would create the directories 'WRF', 'WRF/Run1', and 'WRF/Run1/Data' starting from the current directory even if only
    'WRF' existed.

    Favored over ``os.makedirs(new_dir, exist_ok=True)`` for Python 2 compatibility.

    :param new_dir: the directory path to make; make be relative or absolute. If relative, is interpreted as relative
     to the current directory.
    :type new_dir: str

    :return: None
    """
    dir_parts = new_dir.split(os.pathsep)
    for i in range(len(dir_parts)):
        sub_dir = os.path.join(dir_parts[:i+1])
        if not os.path.isdir(sub_dir):
            os.mkdir(sub_dir)


def _convert_wrf_file(wrf_file, wrfnc2arl_exe, variable_file, output_dir='.',
                      output_pattern=_default_output_pattern):

    """
    Convert a single WRF file to a single ARL file.

    :param wrf_file: the path to the WRF output file to convert.
    :type wrf_file: str

    :param wrfnc2arl_exe: the path to the ``wrfnc2arl`` executable.
    :type wrfnc2arl_exe: str

    :param variable_file: the path to the variable file used by wrfnc2arl (via its ``-P`` option) to map WRF variables
     to ARL variables.
    :type variable_file: str

    :param output_dir: the directory to move the ARL files to.
    :type output_dir: str

    :param output_pattern: the pattern to use to name the ARL files. Both the bracket syntax for string formatting and
     `datetime.strptime` syntax will be applied, with the `datetime` formatting second. The string formatting will give
     the domain number as the ``domain`` keyword.
    :type output_pattern: str

    :return: None
    """
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
    """
    Change a glob pattern string into a regular expression.

    Replaces '*' with '.*' and '?' with '.'

    :param globstr: the glob pattern string to change
    :type globstr: str

    :return: the regular expression string
    :rtype: str
    """
    return globstr.replace('*', '.*').replace('?', '.')


def _build_wrf_file_list(file_pattern, recursive_search=False):
    """
    Build the list of WRF files to convert

    :param file_pattern: the glob pattern to match files against
    :type file_pattern: str

    :param recursive_search: optional, if ``True``, then all directories under the current one are searched for files
     matching ``file_pattern``.
    :type recursive_search: bool

    :return: the list of files
    :rtype: list
    """
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
    """
    Figure out which WRF -> ARL variable table file to use

    :param variable_file: the filename specified by the user
    :type variable_file: str

    :param wrf2arl_dir: the directory containing the wrfnc2arl executable and, more relevantly, the sample variable
     files.
    :type wrf2arl_dir: str

    :return: the path to the variable file. If given as an absolute path or a relative path starting with '.' or '..',
     it is returned unchanged. Otherwise, it is assumed to be the name of a file in the wrf2arl directory; e.g. if given
     'var_sample', then ``os.path.join(wrf2arl_dir, 'var_sample')`` is returned.
    :rtype: str
    :raises RuntimeError: if ``wrf2arl_dir`` is an empty string and it is trying to find a file in that directory, or if
     the specified file does not exist.
    """
    if not os.path.isabs(variable_file) and not variable_file.startswith('.'):
        if wrf2arl_dir == '':
            raise RuntimeError('No wrf2arl directory specified in the config. To indicate a variable file in the '
                               'current directory, prefix the name with "./", e.g. "./var_sample".')
        variable_file = os.path.join(wrf2arl_dir, variable_file)

    if not os.path.isfile(variable_file):
        raise RuntimeError('Specified variable file ({}) does not exist'.format(variable_file))


def drive_wrfnc2arl(file_pattern, arl_variable_file, recursive=False, output_dir='.',
                    output_pattern=_default_output_pattern):
    """
    Main function to drive the bulk conversion of WRF output files to ARL files

    :param file_pattern: a glob pattern to match files against
    :type file_pattern: str

    :param arl_variable_file: the filename for the file mapping WRF -> ARL variables. If given as an absolute path or a
     relative path starting with '.' or '..', it is assumes to be a full path to a file. Otherwise, it is assumed to be
     the name of a file in the wrf2arl directory; e.g. if given 'var_sample', then
     ``os.path.join(wrf2arl_dir, 'var_sample')`` is what is used.
    :type arl_variable_file: str

    :param recursive: optional, if ``True``, then all directories under the current one are searched for files
     matching ``file_pattern``.
    :type recursive: bool

    :param output_dir: the directory to place the ARL files into. If ``recursive = True``, then the directory structure
     of the current directory is mirrored in the output directory.
    :type output_dir: str

    :param output_pattern: the pattern to use to name the output ARL files. Both the bracket syntax for string
     formatting and `datetime.strptime` syntax will be applied, with the `datetime` formatting second. The string
     formatting will give the domain number as the ``domain`` keyword. E.g. "%Y%m%d.%Hz.wrf_d{domain:02}" would be
     transformed into "20160501.00z.wrf_d01" for a domain 1 WRF file on 00:00 May 1, 2016.
    :type output_pattern: str

    :return: None, saves the ARL files in ``output_dir``.
    """
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
    """
    Setup command line arguments for the bulk wrf2arl program.

    :param parser: if given, an argument parser. Generally used if adding this program as a subcommand for a larger
     program, create a new parser as a subparser and pass it to this function. If not given, an argument parser is
     created.
    :type parser: ArgumentParser

    :return: if ``parser`` is not given, the arguments specified on the command line are returned as a dictionary. If
     parser is given, then it is modified in-place to have all the desired command line arguments. In either case, the
     value for 'exec_fxn' will be the driver function to call with the other command line arguments as keyword values.
    :rtype: dict or None.
    """
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
                             'will be replaced with the WRF domain number. Default is "%(default)s".')

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
    """
    Convert a date format string to a regular expression that will match a date in that format.

    For example, "%Y-%m-%d" would be converted to "\d\d\d\d-\d\d-\d\d", matching a four digit year, two digit month, and
    two digit day. Currently only the date format specifiers "%Y", "%m", "%d", "%H", "%M", and "%S" are implemented.

    :param fmt: the date format string to convert
    :type fmt: str

    :return: the regular expression string
    :rtype: str
    """
    replacements = {'%Y': r'\d\d\d\d', '%m': r'\d\d', '%d': r'\d\d', '%H': r'\d\d', '%M': r'\d\d', '%S': r'\d\d'}
    for old, new in replacements.items():
        fmt = fmt.replace(old, new)

    if '%' in fmt:
        raise ValueError('Some time formats not understood. End result was {}'.format(fmt))
    else:
        return fmt


def drive_link_reinit(spinup_time, output_dir, input_dir='.', reinit_pattern=_default_reinit_pattern,
                      arl_pattern=_default_output_pattern):
    """
    Main driver function to link ARL files across multiple reinit subrun directories to one directory

    :param spinup_time: duration from the start of the reinit run to ignore (and not link). Only files for times greater
     than the reinit start time + spinup time are linked.
    :type spinup_time: `datetime.timedelta`

    :param output_dir: the directory to link the ARL files to
    :type output_dir: str

    :param input_dir: the directory containing the reinit directories to link from.
    :type input_dir: str

    :param reinit_pattern: the pattern that a reinit directory name should follow. The directory name must include the
     reinit start time, and the pattern for that start time must be specified here using `datetime.strftime` format
     syntax.
    :type reinit_pattern: str

    :param arl_pattern: the pattern that an ARL filename follows. Must include the format of the file's date using
     `datetime.strftime` format. Currently assumes each ARL file only has one time.
    :type arl_pattern: str

    :return: None
    """
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
    """
    Parse a time string in the format [Nd][Nh][Nm][Ns] into a timedelta.

    :param time_str: the time string to parse
    :type time_str: str

    :return: the corresponding time delta
    :rtype: `datetime.timedelta`
    """
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
    """
    Setup command line arguments for the reinit file linking program.

    :param parser: if given, an argument parser. Generally used if adding this program as a subcommand for a larger
     program, create a new parser as a subparser and pass it to this function. If not given, an argument parser is
     created.
    :type parser: ArgumentParser

    :return: if ``parser`` is not given, the arguments specified on the command line are returned as a dictionary. If
     parser is given, then it is modified in-place to have all the desired command line arguments. In either case, the
     value for 'exec_fxn' will be the driver function to call with the other command line arguments as keyword values.
    :rtype: dict or None.
    """
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
