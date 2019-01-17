from __future__ import print_function, absolute_import, division, unicode_literals

from configobj import ConfigObj
import os

_pkg_dir = os.path.dirname(__file__)
_etc_dir = os.path.join(_pkg_dir, 'etc')

WRF2ARL = 'WRF2ARL'
WRF2ARL_DIR = 'WRFNC2ARL_DIR'


class PyarlConfig(ConfigObj):
    _cfg_file = os.path.join(_etc_dir, 'pyarl.cfg')
    _req_opts = {WRF2ARL: [WRF2ARL_DIR]}
    _comments = {WRF2ARL_DIR: 'The directory where the wrfnc2arl executable is'}

    def __init__(self, filename=None, *args, **kwargs):
        if filename is None and os.path.isfile(self._cfg_file):
            filename = self._cfg_file

        super(PyarlConfig, self).__init__(filename, *args, **kwargs)
        if filename is None:
            filename = self._cfg_file

        self.filename = filename

        self._setup_options()

    def _setup_options(self):
        def get_comment_for_opt(opt):
            comment = self._comments[opt].split('\n')
            for idx, line in enumerate(comment):
                comment[idx] = '# ' + line
            return comment

        for section, options in self._req_opts.items():
            if section not in self:
                self[section] = {k: '' for k in options}
                for opt in options:
                    self[section].comments[opt] = get_comment_for_opt(opt)
            else:
                for opt in options:
                    if opt not in self[section]:
                        self[section][opt] = ''
                        self[section].comments[opt] = get_comment_for_opt(opt)
