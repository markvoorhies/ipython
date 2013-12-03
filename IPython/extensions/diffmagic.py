# -*- coding: utf-8 -*-
"""
======
diffmagic
======

Magic command interface for diffing cells

Usage
=====

``%%diff``

{DIFF_DOC}

"""

#-----------------------------------------------------------------------------
#  Copyright (C) 2012 The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-----------------------------------------------------------------------------

# IPython imports

from IPython.core.magic import Magics, magics_class, line_magic
from IPython.core.displaypub import publish_display_data

from difflib import Differ

@magics_class
class DiffMagics(Magics):
    """A set of magics for diffing notebook cells.
    """

    def __init__(self, shell):
        """
        Parameters
        ----------

        shell : IPython shell
        """
        super(DiffMagics, self).__init__(shell)

        self.differ = Differ()

    @line_magic
    def diff(self, line):
        """Testing
        """

        vals = map(int, line.split())[:2]

        content = [self.shell.history_manager.get_range(0,i,i+1).next()[2]
                   for i in vals]

        diff = self.differ.compare(content[0].splitlines(),
                                   content[1].splitlines())

        publish_display_data('DiffMagic.diff',{'text/plain':"\n".join(diff)})

        return None

def load_ipython_extension(ip):
    """Load the extension in IPython."""
    ip.register_magics(DiffMagics)
