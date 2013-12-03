# -*- coding: utf-8 -*-
"""
======
diffmagic
======

Magic command interface for diffing cells

Usage
=====

``%diff cell1 cell2``

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
import re

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

    def _get_content(self, key):
        try:
            key = int(key)
            return self.shell.history_manager.get_range(0,key,key+1).next()[2]
        except ValueError:
            key_re = re.compile("^[\s]*##label:%s([\s]+.*)?$" % key,re.M)
            for i in reversed(list(self.shell.history_manager.get_range(0))):
                if(key_re.search(i[2]) is not None):
                    return i[2]
            raise KeyError, "Invalid cell label %s" % key

    @line_magic
    def diff(self, line):
        """Render line-based diff of cell1 and cell2, where cell1 and cell2
        are the first two whitespace delimited words in line.
        
        If cell2 is not given, it is the ultimate cell.

        If cell1 is not given, it is the penultimate cell.

        Cell names may be integers, in which case they correspond to
        cell numbers in the kernel's history.

        Otherwise, cell name "x" references the highest numbered cell
        with first line ##label:x (N.B.: this is a place-holder, pending
        a formal system for tagging cells).
        """

        keys = line.split()[:2]

        if(len(keys) > 0):
            cell1 = self._get_content(keys[0])
            if(len(keys) > 1):
                cell2 = self._get_content(keys[1])
            else:
                h = reversed(list(self.shell.history_manager.get_range(0)))
                # burn current cell
                dummy = h.next()
                cell2 = h.next()[2]
        else:
            assert(self.shell.history_length > 1)
            h = reversed(list(self.shell.history_manager.get_range(0)))
            # burn current cell
            dummy = h.next()
            cell2 = h.next()[2]
            cell1 = h.next()[2]

        diff = self.differ.compare(cell1.splitlines(),cell2.splitlines())

        publish_display_data('DiffMagic.diff',{'text/plain':"\n".join(diff)})

        return None

def load_ipython_extension(ip):
    """Load the extension in IPython."""
    ip.register_magics(DiffMagics)
