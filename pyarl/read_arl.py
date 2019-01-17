from __future__ import print_function, absolute_import, division, unicode_literals

import numpy as np

#TODO: test with 16-bit files


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
_record_header_format = [('year', 2, int),
                         ('month', 2, int),
                         ('day', 2, int),
                         ('hour', 2, int),
                         (None, 2, int),
                         (None, 2, int),
                         (None, 2, int),
                         ('kvar', 4, _decode_bytes),
                         ('scale_exp', 4, int),
                         ('precision', 14, float),
                         ('initial_value', 14, float)]


_grid_header_format = [('data_source', 4, _decode_bytes),
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
        record header - a list of dictionaries containing the information about each of the records, including the index
         record at the start of the file.
        index header - a dictionary containing the information for this index in the file.
        level headers - a list of dictionaries giving the level height and list of variables at each model level.
    """

    with open(filename, 'rb') as fhandle:
        record_hdr, grid_hdr, level_hdrs = _read_arl_header(fhandle)

        _advance_to_first_var(fhandle)

        nx = grid_hdr['n_x_points']
        ny = grid_hdr['n_y_points']
        nz = grid_hdr['n_levels']
        data = _make_empty_arrays_for_vars(level_hdrs, nx, ny, nz)

        record_hdr += _read_data(fhandle, data, level_hdrs)

    return data, record_hdr, grid_hdr, level_hdrs


def _read_arl_header(fhandle):
    """
    Read the initial headers in the ARL file.

    At the beginning of the ARL file, there's three headers: the index record header, the index header itself, and the
    level headers. The index header primarily contains information about the grid, the levels header contains information
    about the variables present at each level.

    :param fhandle: the file handle to the ARL file. Should be at the beginning of the file.
    :type fhandle: file handle

    :return: the first record header, the index header, and the level header information
    :rtype: dict, dict, list
    """
    file_hdr = _read_record_header(fhandle)
    if file_hdr['kvar'] != 'INDX':
        raise ARLFormatException('This appears to be an old-style file (z-dim variable is not "INDX"). '
                                 'These are not supported.')
    grid_hdr = _read_grid_header(fhandle)
    level_hdrs = _read_level_info(fhandle, grid_hdr['n_levels'])
    return file_hdr, grid_hdr, level_hdrs


def _advance_to_first_var(fhandle, is_big_endian=False):
    """
    Move the file handle for the ARL file to the beginning of the variable records.

    :param fhandle: the handle to the ARL file. Must be at the end of the initial headers
    :type fhandle: file handle

    :param is_big_endian: controls whether to
    :return:
    """
    endian = 'big' if is_big_endian else 'little'

    def _get_byte():
        return int.from_bytes(fhandle.read(1), endian)

    # There's a block of null values between the level header and the first variable. It seems to be different lengths
    # in different files. Until I find a way of figuring out it's length a priori, I'm going to skip over it by scanning
    # through the file until we hit a non-null character. Note that '0' is not a null character, '\x00' (that has a
    # numeric value of 0) is.

    # todo: look into what writes that block of null characters, see if its length can be predicted
    b = _get_byte()
    while b == 0:
        b = _get_byte()

    # back up one byte
    fhandle.seek(-1, 1)


def _read_record_header(fhandle):
    """
    Read the 50 ASCII bytes at the beginning of a variable record.

    Each ARL file begins with a record header that defines the index, and then each variable at each level begins with
    a record header that indicates what variable is being read, along with the first value, the precision, scaling
    factor, etc. This function reads that information and converts it to a dictionary.

    :param fhandle: the handle to an ARL file. Must be at the beginning of a record.
    :type fhandle: file handle

    :return: a dictionary containing the record information.
    """
    header_info = _read_header_info(fhandle, _record_header_format, nbytes_total=50)
    return header_info


def _read_grid_header(fhandle, allow_failed_conversions=False):
    """
    Read the header that defines the spatial grid for the data.

    After the initial record header, an ARL file has a header than defines the 3D grid that the variables exist on. This
    function reads that header.

    :param fhandle: a handle to an ARL file. Must be positioned at the beginning of the grid header; i.e., the first
     call to `_read_record_header` must have completed.
    :type fhandle: file handle

    :param allow_failed_conversions: optional, allows you to suppress errors if a piece of information cannot be
     converted. Instead, it will print a message informing you of the problem and try the next piece of information.
     Setting this to ``True``  is useful for debugging, but should not be used when reading data for research purposes,
     as errors when converting the header data mean something has gone very wrong.
    :type allow_failed_conversions: bool

    :return: a dictionary with the information about the grid
    """
    return _read_header_info(fhandle, _grid_header_format, nbytes_total=108, allow_failed_conversions=allow_failed_conversions)


def _read_level_info(fhandle, nlevels):
    """
    Read the block of ASCII text that defines the vertical levels in the file and what variables are present at each level

    :param fhandle: a handle to an ARL file, it must be at the start of the level information in the file (i.e.
     `_read_grid_header` must have completed).
    :type fhandle: file handle

    :param nlevels: the number of levels in the file, read from the index header
    :type nlevels: int

    :return: a list of dictionaries, where each dictionary contains the information about one level.
    """
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


def _read_level_header(fhandle):
    """
    Read a single level's header information.

    Helper function for `_read_level_info` that handles a single level's header information

    :param fhandle: the ARL file handle to read from. Must be positioned at the start of a level header
    :type fhandle: file handle

    :return: a dictionary describing the information for that level.
    """
    return _read_header_info(fhandle, _level_header_format)


def _read_variable_header(fhandle):
    """
    Read a single variable's header information.

    This is a helper function for `_read_level_info` that reads a single variable's header info. The full level header
    has many such headers per grid level.

    :param fhandle: the ARL file handle to read from. Must be positioned at the start of a level header
    :type fhandle: file handle

    :return: a dictionary describing the information for that variable
    """
    return _read_header_info(fhandle, _variable_header_format)


def _read_header_info(fhandle, format_spec, nbytes_total=None, allow_failed_conversions=False):
    """
    Generic function to read header information given a dictionary defining its format.

    This function uses a list of tuples to define how to read header bytes from an ARL file. The list (``format_spec``)
    must consist of tuples, where the first element specifies the key to store the read value under in the output
    dictionary, the second specifies the number of bytes to read, and the third specifies a function that, when called
    with those bytes as the only argument, process and return the desired value. For example::

        format_spec = [('variable_name', 4, _decode_bytes),
                       ('checksum', 3, int),
                       (None, 1, None)]

    would read the next four bytes from the file pointed to by ``fhandle``, pass them to `_decode_bytes`, and store the
    resulting value in the return dict under the key `'variable_name'`. Likewise, the next 3 bytes would be converted to
    an integer and stored as `'checksum'`. The last row is a special case; when the first element of the tuple is
    ``None``, then the specified number of bytes (in this case, 1) is read, but nothing is done with it. This is useful
    to skip over spacing bytes or bytes that we don't consider relevant.

    :param fhandle: a handle to an ARL file to read the header from. Must be positioned at the beginning of the header.
    :type fhandle: file handle

    :param format_spec: a list of tuples which describe how to read the header. See above for details.
    :type format_spec: list of tuples

    :param nbytes_total: optional, specifies a total number of bytes that make up the header. This, is given, has two
     effects. First, if fewer than this many bytes are specified to be read by format_spec, then at the end of the
     function, the remaining bytes will be read and ignored. This way if, e.g. only the first 10 of 50 bytes are
     actually useful in a header, ``format_spec`` doesn't have to include a line for those extra 40 bytes. Second, if
     ``format_spec`` specifies more than ``nbytes_total`` to read, an error is raised. Both of these behaviors ensure
     that the location of the reading pointer for ``fhandle`` ends up in the right place.
    :type nbytes_total: int

    :param allow_failed_conversions: optional, allows you to suppress errors if a piece of information cannot be
     converted. Instead, it will print a message informing you of the problem and try the next piece of information.
     Setting this to ``True``  is useful for debugging, but should not be used when reading data for research purposes,
     as errors when converting the header data mean something has gone very wrong.
    :type allow_failed_conversions: bool

    :return: a dictionary containing the header values
    :rtype: dict

    :raises ARLFormatException: if the total number of bytes specified by ``format_spec`` exceeds ``nbytes_total``.
    """
    header_info = dict()
    for key, nbytes, convert_fxn in format_spec:
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
    """
    Read the next data value in the ARL file.

    ARL files store data in 8 or 16 bytes per value as a scaled difference from the previous value in the array. In
    theory, this allows the data to be store with significantly fewer bits without much loss of precision, since
    generally geophysical fields vary smoothly in space, so only the least significant bits need to be stored for each
    value. This function handles unpacking those compressed values into their full values.

    :param fhandle: a handle to the ARL file, where the next byte (or two bytes, if ``is_16bit = True`` are data.
    :type fhandle: file handle

    :param last_value: the value that this value is a difference from, i.e. the value returned will be :math:`l + v`
     where :math:`l` is ``last_value`` and :math:`v` is the the unpacked difference stored in the next byte(s).
    :type last_value: float

    :param precision: the precision of this variable. Read from the variable header. If the absolute value to be
     returned is less than this magnitude, then 0.0 is returned instead.
    :type precision: float

    :param scale_exp: the integer factor used to set the scaling factor for this value. Read from the variable's header.
    :type scale_exp: int or float

    :param is_16bit: optional (default ``False``), controls whether to read one or two bytes. Set to ``True`` for the
     latter. Note: behavior for ``True`` untested.
    :type is_16bit: bool

    :param is_big_endian: optional (default ``False``), controls whether to interpret the bytes read as big- or little-
     endian. As far as I can tell, whether the files are written as big- or little- endian depends on the system the
     ARL file is written on. Little endian is more common, so is the default. Set this to ``True`` to assume big-endian
     instead. Note: big-endian reading not tested.

    :return: the unpacked value
    :rtype: float
    """
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
    """
    Helper function to create empty arrays that the unpacked data will be placed into.

    :param level_headers: the list of level header dictionaries that define what variables are defined on each level.
    :type level_headers: list of dicts

    :param nx: the number of grid points in the x-direction
    :type nx: int

    :param ny: the number of grid points in the y-direction
    :type ny: int

    :param n_levels: the total number of levels defined in the ARL file.
    :type n_levels: int

    :return: a dictionary (keys are ARL variable names) with a NaN-filled numpy array for each. Currently, variables
     only defined in the first (surface) level will be :math:`n_x \times n_y \times 1`; variables defined on any other
     level will be :math:`n_x \times n_y \times n_z` where :math:`n_z` is ``n_levels``.
    :rtype: dict of numpy arrays.
    """
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


def _read_data(fhandle, var_arrays, level_headers, is_16bit=False, is_big_endian=False):
    """
    Read all the packed data in the ARL file.

    :param fhandle: the handle to the ARL file; must be at the start of the record header for the first variable.
    :type fhandle: file handle

    :param var_arrays: the dictionary of numpy arrays to place the data into. This is the dict initialized by
     `_make_empty_arrays_for_vars`.
    :type var_arrays: dict of numpy arrays

    :param level_headers: the list of level headers that define what variables are present in each level and in what
     order.
    :type level_headers: list of dicts

    :param is_16bit: optional (default ``False``), controls whether to read one or two bytes. Set to ``True`` for the
     latter. Note: behavior for ``True`` untested.
    :type is_16bit: bool

    :param is_big_endian: optional (default ``False``), controls whether to interpret the bytes read as big- or little-
     endian. As far as I can tell, whether the files are written as big- or little- endian depends on the system the
     ARL file is written on. Little endian is more common, so is the default. Set this to ``True`` to assume big-endian
     instead. Note: big-endian reading not tested.
    :type is_big_endian: bool

    :return: a list of the individual record header dictionaries. ``var_arrays`` is modified in-place to insert the
     data values.
    :rtype: list of dicts
    """
    record_headers = []

    for klev, level in enumerate(level_headers):
        k = klev if klev == 0 else klev - 1
        for variable in level['variables']:
            record_hdr = _read_record_header(fhandle)
            record_headers.append(record_hdr)
            name = variable['variable_name']
            var_arr = var_arrays[name]
            (last_val, precision, scale_exp) = (record_hdr['initial_value'], record_hdr['precision'], record_hdr['scale_exp'])
            for j in range(var_arr.shape[1]):
                for i in range(var_arr.shape[0]):
                    last_val = _read_next_value(fhandle, last_val, precision, scale_exp, is_16bit=is_16bit,
                                                is_big_endian=is_big_endian)
                    var_arr[i, j, k] = last_val
                last_val = var_arr[0, j, k].item()

    return record_headers
