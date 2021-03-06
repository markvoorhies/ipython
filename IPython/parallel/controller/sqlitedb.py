"""A TaskRecord backend using sqlite3"""
#-----------------------------------------------------------------------------
#  Copyright (C) 2011  The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-----------------------------------------------------------------------------

import json
import os
import cPickle as pickle
from datetime import datetime

import sqlite3

from zmq.eventloop import ioloop

from IPython.utils.traitlets import CUnicode, CStr, Instance, List
from .dictdb import BaseDB
from IPython.parallel.util import ISO8601

#-----------------------------------------------------------------------------
# SQLite operators, adapters, and converters
#-----------------------------------------------------------------------------

operators = {
 '$lt' : "<",
 '$gt' : ">",
 # null is handled weird with ==,!=
 '$eq' : "=",
 '$ne' : "!=",
 '$lte': "<=",
 '$gte': ">=",
 '$in' : ('=', ' OR '),
 '$nin': ('!=', ' AND '),
 # '$all': None,
 # '$mod': None,
 # '$exists' : None
}
null_operators = {
'=' : "IS NULL",
'!=' : "IS NOT NULL",
}

def _adapt_datetime(dt):
    return dt.strftime(ISO8601)

def _convert_datetime(ds):
    if ds is None:
        return ds
    else:
        return datetime.strptime(ds, ISO8601)

def _adapt_dict(d):
    return json.dumps(d)

def _convert_dict(ds):
    if ds is None:
        return ds
    else:
        return json.loads(ds)

def _adapt_bufs(bufs):
    # this is *horrible*
    # copy buffers into single list and pickle it:
    if bufs and isinstance(bufs[0], (bytes, buffer)):
        return sqlite3.Binary(pickle.dumps(map(bytes, bufs),-1))
    elif bufs:
        return bufs
    else:
        return None

def _convert_bufs(bs):
    if bs is None:
        return []
    else:
        return pickle.loads(bytes(bs))

#-----------------------------------------------------------------------------
# SQLiteDB class
#-----------------------------------------------------------------------------

class SQLiteDB(BaseDB):
    """SQLite3 TaskRecord backend."""
    
    filename = CUnicode('tasks.db', config=True)
    location = CUnicode('', config=True)
    table = CUnicode("", config=True)
    
    _db = Instance('sqlite3.Connection')
    _keys = List(['msg_id' ,
            'header' ,
            'content',
            'buffers',
            'submitted',
            'client_uuid' ,
            'engine_uuid' ,
            'started',
            'completed',
            'resubmitted',
            'result_header' ,
            'result_content' ,
            'result_buffers' ,
            'queue' ,
            'pyin' ,
            'pyout',
            'pyerr',
            'stdout',
            'stderr',
        ])
    
    def __init__(self, **kwargs):
        super(SQLiteDB, self).__init__(**kwargs)
        if not self.table:
            # use session, and prefix _, since starting with # is illegal
            self.table = '_'+self.session.replace('-','_')
        if not self.location:
            if hasattr(self.config.Global, 'cluster_dir'):
                self.location = self.config.Global.cluster_dir
            else:
                self.location = '.'
        self._init_db()
        
        # register db commit as 2s periodic callback
        # to prevent clogging pipes
        # assumes we are being run in a zmq ioloop app
        loop = ioloop.IOLoop.instance()
        pc = ioloop.PeriodicCallback(self._db.commit, 2000, loop)
        pc.start()
    
    def _defaults(self, keys=None):
        """create an empty record"""
        d = {}
        keys = self._keys if keys is None else keys
        for key in keys:
            d[key] = None
        return d
    
    def _init_db(self):
        """Connect to the database and get new session number."""
        # register adapters
        sqlite3.register_adapter(datetime, _adapt_datetime)
        sqlite3.register_converter('datetime', _convert_datetime)
        sqlite3.register_adapter(dict, _adapt_dict)
        sqlite3.register_converter('dict', _convert_dict)
        sqlite3.register_adapter(list, _adapt_bufs)
        sqlite3.register_converter('bufs', _convert_bufs)
        # connect to the db
        dbfile = os.path.join(self.location, self.filename)
        self._db = sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES, 
            # isolation_level = None)#,
             cached_statements=64)
        # print dir(self._db)
        
        self._db.execute("""CREATE TABLE IF NOT EXISTS %s 
                (msg_id text PRIMARY KEY,
                header dict text,
                content dict text,
                buffers bufs blob,
                submitted datetime text,
                client_uuid text,
                engine_uuid text,
                started datetime text,
                completed datetime text,
                resubmitted datetime text,
                result_header dict text,
                result_content dict text,
                result_buffers bufs blob,
                queue text,
                pyin text,
                pyout text,
                pyerr text,
                stdout text,
                stderr text)
                """%self.table)
        self._db.commit()
    
    def _dict_to_list(self, d):
        """turn a mongodb-style record dict into a list."""
        
        return [ d[key] for key in self._keys ]
    
    def _list_to_dict(self, line, keys=None):
        """Inverse of dict_to_list"""
        keys = self._keys if keys is None else keys
        d = self._defaults(keys)
        for key,value in zip(keys, line):
            d[key] = value
        
        return d
    
    def _render_expression(self, check):
        """Turn a mongodb-style search dict into an SQL query."""
        expressions = []
        args = []
        
        skeys = set(check.keys())
        skeys.difference_update(set(self._keys))
        skeys.difference_update(set(['buffers', 'result_buffers']))
        if skeys:
            raise KeyError("Illegal testing key(s): %s"%skeys)
        
        for name,sub_check in check.iteritems():
            if isinstance(sub_check, dict):
                for test,value in sub_check.iteritems():
                    try:
                        op = operators[test]
                    except KeyError:
                        raise KeyError("Unsupported operator: %r"%test)
                    if isinstance(op, tuple):
                        op, join = op
                    
                    if value is None and op in null_operators:
                            expr = "%s %s"%null_operators[op]
                    else:
                        expr = "%s %s ?"%(name, op)
                        if isinstance(value, (tuple,list)):
                            if op in null_operators and any([v is None for v in value]):
                                # equality tests don't work with NULL
                                raise ValueError("Cannot use %r test with NULL values on SQLite backend"%test)
                            expr = '( %s )'%( join.join([expr]*len(value)) )
                            args.extend(value)
                        else:
                            args.append(value)
                    expressions.append(expr)
            else:
                # it's an equality check
                if sub_check is None:
                    expressions.append("%s IS NULL")
                else:
                    expressions.append("%s = ?"%name)
                    args.append(sub_check)
        
        expr = " AND ".join(expressions)
        return expr, args
    
    def add_record(self, msg_id, rec):
        """Add a new Task Record, by msg_id."""
        d = self._defaults()
        d.update(rec)
        d['msg_id'] = msg_id
        line = self._dict_to_list(d)
        tups = '(%s)'%(','.join(['?']*len(line)))
        self._db.execute("INSERT INTO %s VALUES %s"%(self.table, tups), line)
        # self._db.commit()
    
    def get_record(self, msg_id):
        """Get a specific Task Record, by msg_id."""
        cursor = self._db.execute("""SELECT * FROM %s WHERE msg_id==?"""%self.table, (msg_id,))
        line = cursor.fetchone()
        if line is None:
            raise KeyError("No such msg: %r"%msg_id)
        return self._list_to_dict(line)
    
    def update_record(self, msg_id, rec):
        """Update the data in an existing record."""
        query = "UPDATE %s SET "%self.table
        sets = []
        keys = sorted(rec.keys())
        values = []
        for key in keys:
            sets.append('%s = ?'%key)
            values.append(rec[key])
        query += ', '.join(sets)
        query += ' WHERE msg_id == ?'
        values.append(msg_id)
        self._db.execute(query, values)
        # self._db.commit()
    
    def drop_record(self, msg_id):
        """Remove a record from the DB."""
        self._db.execute("""DELETE FROM %s WHERE msg_id==?"""%self.table, (msg_id,))
        # self._db.commit()
    
    def drop_matching_records(self, check):
        """Remove a record from the DB."""
        expr,args = self._render_expression(check)
        query = "DELETE FROM %s WHERE %s"%(self.table, expr)
        self._db.execute(query,args)
        # self._db.commit()
        
    def find_records(self, check, keys=None):
        """Find records matching a query dict, optionally extracting subset of keys.
        
        Returns list of matching records.
        
        Parameters
        ----------
        
        check: dict
            mongodb-style query argument
        keys: list of strs [optional]
            if specified, the subset of keys to extract.  msg_id will *always* be
            included.
        """
        if keys:
            bad_keys = [ key for key in keys if key not in self._keys ]
            if bad_keys:
                raise KeyError("Bad record key(s): %s"%bad_keys)
        
        if keys:
            # ensure msg_id is present and first:
            if 'msg_id' in keys:
                keys.remove('msg_id')
            keys.insert(0, 'msg_id')
            req = ', '.join(keys)
        else:
            req = '*'
        expr,args = self._render_expression(check)
        query = """SELECT %s FROM %s WHERE %s"""%(req, self.table, expr)
        cursor = self._db.execute(query, args)
        matches = cursor.fetchall()
        records = []
        for line in matches:
            rec = self._list_to_dict(line, keys)
            records.append(rec)
        return records
    
    def get_history(self):
        """get all msg_ids, ordered by time submitted."""
        query = """SELECT msg_id FROM %s ORDER by submitted ASC"""%self.table
        cursor = self._db.execute(query)
        # will be a list of length 1 tuples
        return [ tup[0] for tup in cursor.fetchall()]

__all__ = ['SQLiteDB']