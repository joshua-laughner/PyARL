from __future__ import print_function, absolute_import, division, unicode_literals

import numpy as np

import pdb

class ARLFormatException(Exception):
    """
    Exception for unexpected errors reading ARL files
    """
    pass


def _do_nothing(b):
    """
    Dummy parsing function that doesn't actually change the bytes read in
    :param b: bytes string
    :return: the unaltered bytes string
    """
    return b


def _decode_bytes(b):
    """
    Decode a bytes string to a regular string, assuming it is ASCII encoded.
    :param b: the bytes to decode
    :return: the decoded string
    """
    return b.decode('ascii')


# Relying heavily on descriptions of ARL format at https://www.ready.noaa.gov/HYSPLIT_data2arl.php#INFO
# and the pdf referenced in the post https://hysplitbbs.arl.noaa.gov/viewtopic.php?t=48

# All the format lists must be lists of tuples where the first element of the tuple is the key to use in the final
# dictionary, the second element is the number of bytes to read, and the third element is the function to call to
# convert the bytes into a usable format. Setting the first element to None will read the number of bytes specified,
# but not do anything with them.
_file_header_format = [('year', 2, int),
                       ('month', 2, int),
                       ('day', 2, int),
                       ('hour', 2, int),
                       (None, 2, int),
                       (None, 2, int),
                       (None, 2, int),
                       ('kvar', 4, _decode_bytes),
                       ('scale_exp', 4, int),
                       ('precision', 7, float),
                       ('initial_value', 7, float)]


_index_header_format = [('data_source', 4, _decode_bytes),
                        ('forecast_hour', 3, int),
                        ('data_minutes', 2, int),
                        ('pole_lat', 7, float),
                        ('pole_lon', 7, float),
                        ('tangent_lat', 7, float),
                        ('tangent_lon', 7, float),
                        ('grid_size', 7, float),
                        ('orientation', 7, float),
                        ('cone_angle', 7, float),
                        ('xsync_point', 7, float),
                        ('ysync_point', 7, float),
                        ('sync_point_lat', 7, float),
                        ('sync_point_lon', 7, float),
                        (None, 7, _do_nothing),
                        ('n_x_points', 3, int),
                        ('n_y_points', 3, int),
                        ('n_levels', 3, int),
                        ('vertical_coord_sys_flag', 2, int),
                        ('index_record_length', 4, int)]


_level_header_format = [('level_height', 6, float),
                        ('n_var_at_level', 2, int)]

_variable_header_format = [('variable_name', 4, _decode_bytes),
                           ('checksum', 3, int),
                           (None, 1, _do_nothing)]


def read_arl(filename):
    """
    Read in an ARL file.
    :param filename: the ARL file to read
    :type filename: str

    :return: data, file header, index header, level headers
        data - a dictionary of numpy arrays with the value for each variable
        file header - a dictionary containing the information in the file header section
        index header - a dictionary containing the information for this index in the file.
        level headers - a list of dictionaries giving the level height and list of variables at each model level.
    """

    with open(filename, 'rb') as fhandle:
        file_hdr, index_hdr, level_hdrs = _read_arl_header(fhandle)

        nx = index_hdr['n_x_points']
        ny = index_hdr['n_y_points']
        nz = index_hdr['n_levels']
        data = _make_empty_arrays_for_vars(level_hdrs, nx, ny, nz)

        init_val = file_hdr['initial_value']
        precision = file_hdr['precision']
        scale_exp = file_hdr['scale_exp']
        _read_data(fhandle, data, level_hdrs, init_val, precision, scale_exp)

    return data, file_hdr, index_hdr, level_hdrs


def _read_arl_header(fhandle):
    file_hdr = _read_file_header(fhandle)
    index_hdr = _read_index_header(fhandle)
    level_hdrs = _read_level_info(fhandle, index_hdr['n_levels'])
    return file_hdr, index_hdr, level_hdrs


def _read_level_info(fhandle, nlevels):
    level_info = []
    for i in range(nlevels):
        header_info = _read_level_header(fhandle)
        nvars = header_info['n_var_at_level']
        var_info = []
        for j in range(nvars):
            var_info.append(_read_variable_header(fhandle))
        header_info['variables'] = var_info
        level_info.append(header_info)
    return level_info


def _read_file_header(fhandle):
    header_info = _read_header_info(fhandle, _file_header_format, nbytes_total=50)
    if header_info['kvar'] != 'INDX':
        raise ARLFormatException('This appears to be an old-style file (z-dim variable is not "INDX"). '
                                 'These are not supported.')
    return header_info


def _read_index_header(fhandle, allow_failed_conversions=False):
    return _read_header_info(fhandle, _index_header_format, nbytes_total=108, allow_failed_conversions=allow_failed_conversions)


def _read_level_header(fhandle):
    return _read_header_info(fhandle, _level_header_format)


def _read_variable_header(fhandle):
    return _read_header_info(fhandle, _variable_header_format)


def _read_header_info(fhandle, format_dict, nbytes_total=None, allow_failed_conversions=False):
    header_info = dict()
    for key, nbytes, convert_fxn in format_dict:
        raw_bytes = fhandle.read(nbytes)
        # Unless a total number of bytes to read was not specified, keep track of how many bytes we've read
        if nbytes_total is not None:
            nbytes_total -= nbytes
            if nbytes_total < 0:
                raise ARLFormatException("The number of bytes to read defined in the format dictionary exceeded the "
                                         "total number of bytes allowed to read")

        # Allow the key to be None to indicate bytes that we need to read to advance the read point in the file, but
        # that we don't actually care about. These could be spacer bytes or just bytes we don't know or don't care what
        # they represent.
        if key is not None:
            try:
                val = convert_fxn(raw_bytes)
            except ValueError as err:
                if allow_failed_conversions:
                    print('Conversion of key "{key}" failed, raw bytes = "{b}"'.format(key=key, b=raw_bytes))
                    val = raw_bytes
                else:
                    raise err
            header_info[key] = val

    # Read any remaining bytes we need. This way, if we say that a header is e.g. 50 bytes but only specify the first 10
    # because those are the only ones we care about, we make sure we advance the reading point to the end of this
    # record.
    if nbytes_total is not None:
        fhandle.read(nbytes_total)

    return header_info


def _read_next_value(fhandle, last_value, precision, scale_exp, is_16bit=False, is_big_endian=False):
    endian = 'big' if is_big_endian else 'little'
    if is_16bit:
        # We could do int.from_bytes(fhandle.read(2)), except that in unpack_subs.f in the ARL fortran data package
        # the two bytes are read in separately. As long as they were written little-endian, then reading both bytes at
        # once would still work. However, I'm concerned that if the code that writes 16-bit ARL files manually separates
        # them into the two bytes, then the individual bytes could be written big-endian while the order they're written
        # is little-endian. That is, little endian should always write the bits as:
        #
        #   abcdefgh ijklmnop
        #
        # (a=least significant byte, p=most significant), but big endian might result in:
        #
        #   hgfedcba ponmlkji
        #
        # instead of the true big-endian
        #
        #   ponmlkji hgfedcba
        byte1 = int.from_bytes(fhandle.read(1), endian, signed=False)
        byte2 = int.from_bytes(fhandle.read(1), endian, signed=False)
        val = byte2 * 256 + byte1
        scale = 2.0 ** (15 - scale_exp)
        val = (float(val) - 32767.0) / scale + last_value
    else:
        val = int.from_bytes(fhandle.read(1), endian, signed=False)
        scale = 2.0 ** (7.0 - scale_exp)
        val = (float(val) - 127.0) / scale + last_value

    if abs(val) < precision:
        val = 0.0

    return val


def _make_empty_arrays_for_vars(level_headers, nx, ny, n_levels):
    var_dims = dict()
    # for now, we assume that all variables are either surface only or in all layers
    # todo: check level headers to verify that
    variables = level_headers[0]['variables']
    for v in variables:
        name = v['variable_name']
        var_dims[name] = 1

    variables = level_headers[-1]['variables']

    for v in variables:
        name = v['variable_name']
        var_dims[name] = n_levels

    var_arrays = dict()
    for name, zdim in var_dims.items():
        var_arrays[name] = np.full((nx, ny, zdim), np.nan)

    return var_arrays


def _read_data(fhandle, var_arrays, level_headers, initial_value, precision, scale_exp, is_16bit=False, is_big_endian=False):
    for k, level in enumerate(level_headers):
        for variable in level['variables']:
            name = variable['variable_name']
            var_arr = var_arrays[name]
            #pdb.set_trace()
            last_val = initial_value
            for j in range(var_arr.shape[1]):
                for i in range(var_arr.shape[0]):
                    last_val = _read_next_value(fhandle, last_val, precision, scale_exp, is_16bit=is_16bit,
                                                is_big_endian=is_big_endian)
                    var_arr[i, j, k] = last_val
                last_val = var_arr[0, j, k].item()
