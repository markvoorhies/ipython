"""Tests for db backends"""

#-------------------------------------------------------------------------------
#  Copyright (C) 2011  The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-------------------------------------------------------------------------------

#-------------------------------------------------------------------------------
# Imports
#-------------------------------------------------------------------------------


import tempfile
import time

from datetime import datetime, timedelta
from unittest import TestCase

from nose import SkipTest

from IPython.parallel import error, streamsession as ss
from IPython.parallel.controller.dictdb import DictDB
from IPython.parallel.controller.sqlitedb import SQLiteDB
from IPython.parallel.controller.hub import init_record, empty_record

#-------------------------------------------------------------------------------
# TestCases
#-------------------------------------------------------------------------------

class TestDictBackend(TestCase):
    def setUp(self):
        self.session = ss.StreamSession()
        self.db = self.create_db()
        self.load_records(16)
    
    def create_db(self):
        return DictDB()
    
    def load_records(self, n=1):
        """load n records for testing"""
        #sleep 1/10 s, to ensure timestamp is different to previous calls
        time.sleep(0.1)
        msg_ids = []
        for i in range(n):
            msg = self.session.msg('apply_request', content=dict(a=5))
            msg['buffers'] = []
            rec = init_record(msg)
            msg_ids.append(msg['msg_id'])
            self.db.add_record(msg['msg_id'], rec)
        return msg_ids
    
    def test_add_record(self):
        before = self.db.get_history()
        self.load_records(5)
        after = self.db.get_history()
        self.assertEquals(len(after), len(before)+5)
        self.assertEquals(after[:-5],before)
        
    def test_drop_record(self):
        msg_id = self.load_records()[-1]
        rec = self.db.get_record(msg_id)
        self.db.drop_record(msg_id)
        self.assertRaises(KeyError,self.db.get_record, msg_id)
    
    def _round_to_millisecond(self, dt):
        """necessary because mongodb rounds microseconds"""
        micro = dt.microsecond
        extra = int(str(micro)[-3:])
        return dt - timedelta(microseconds=extra)
    
    def test_update_record(self):
        now = self._round_to_millisecond(datetime.now())
        # 
        msg_id = self.db.get_history()[-1]
        rec1 = self.db.get_record(msg_id)
        data = {'stdout': 'hello there', 'completed' : now}
        self.db.update_record(msg_id, data)
        rec2 = self.db.get_record(msg_id)
        self.assertEquals(rec2['stdout'], 'hello there')
        self.assertEquals(rec2['completed'], now)
        rec1.update(data)
        self.assertEquals(rec1, rec2)
    
    # def test_update_record_bad(self):
    #     """test updating nonexistant records"""
    #     msg_id = str(uuid.uuid4())
    #     data = {'stdout': 'hello there'}
    #     self.assertRaises(KeyError, self.db.update_record, msg_id, data)

    def test_find_records_dt(self):
        """test finding records by date"""
        hist = self.db.get_history()
        middle = self.db.get_record(hist[len(hist)/2])
        tic = middle['submitted']
        before = self.db.find_records({'submitted' : {'$lt' : tic}})
        after = self.db.find_records({'submitted' : {'$gte' : tic}})
        self.assertEquals(len(before)+len(after),len(hist))
        for b in before:
            self.assertTrue(b['submitted'] < tic)
        for a in after:
            self.assertTrue(a['submitted'] >= tic)
        same = self.db.find_records({'submitted' : tic})
        for s in same:
            self.assertTrue(s['submitted'] == tic)
    
    def test_find_records_keys(self):
        """test extracting subset of record keys"""
        found = self.db.find_records({'msg_id': {'$ne' : ''}},keys=['submitted', 'completed'])
        for rec in found:
            self.assertEquals(set(rec.keys()), set(['msg_id', 'submitted', 'completed']))
    
    def test_find_records_msg_id(self):
        """ensure msg_id is always in found records"""
        found = self.db.find_records({'msg_id': {'$ne' : ''}},keys=['submitted', 'completed'])
        for rec in found:
            self.assertTrue('msg_id' in rec.keys())
        found = self.db.find_records({'msg_id': {'$ne' : ''}},keys=['submitted'])
        for rec in found:
            self.assertTrue('msg_id' in rec.keys())
        found = self.db.find_records({'msg_id': {'$ne' : ''}},keys=['msg_id'])
        for rec in found:
            self.assertTrue('msg_id' in rec.keys())
    
    def test_find_records_in(self):
        """test finding records with '$in','$nin' operators"""
        hist = self.db.get_history()
        even = hist[::2]
        odd = hist[1::2]
        recs = self.db.find_records({ 'msg_id' : {'$in' : even}})
        found = [ r['msg_id'] for r in recs ]
        self.assertEquals(set(even), set(found))
        recs = self.db.find_records({ 'msg_id' : {'$nin' : even}})
        found = [ r['msg_id'] for r in recs ]
        self.assertEquals(set(odd), set(found))
    
    def test_get_history(self):
        msg_ids = self.db.get_history()
        latest = datetime(1984,1,1)
        for msg_id in msg_ids:
            rec = self.db.get_record(msg_id)
            newt = rec['submitted']
            self.assertTrue(newt >= latest)
            latest = newt
        msg_id = self.load_records(1)[-1]
        self.assertEquals(self.db.get_history()[-1],msg_id)
    
    def test_datetime(self):
        """get/set timestamps with datetime objects"""
        msg_id = self.db.get_history()[-1]
        rec = self.db.get_record(msg_id)
        self.assertTrue(isinstance(rec['submitted'], datetime))
        self.db.update_record(msg_id, dict(completed=datetime.now()))
        rec = self.db.get_record(msg_id)
        self.assertTrue(isinstance(rec['completed'], datetime))

    def test_drop_matching(self):
        msg_ids = self.load_records(10)
        query = {'msg_id' : {'$in':msg_ids}}
        self.db.drop_matching_records(query)
        recs = self.db.find_records(query)
        self.assertTrue(len(recs)==0)
            
class TestSQLiteBackend(TestDictBackend):
    def create_db(self):
        return SQLiteDB(location=tempfile.gettempdir())
    
    def tearDown(self):
        self.db._db.close()
