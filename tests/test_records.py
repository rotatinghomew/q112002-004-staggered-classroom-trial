import unittest

from record_reader import read_records


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tables = read_records()

    def references(self, left, left_key, right, right_key):
        candidates = {row[right_key] for row in self.tables[right]}
        self.assertTrue(all(row[left_key] in candidates for row in self.tables[left]))

    def test_documents_reference_source_records(self):
        self.references('enrollment','room','assignment','room')
        self.references('observations','student','enrollment','student')
        self.references('moves','to_room','assignment','room')
        groups = {(row['week'],row['block']) for row in self.tables['assignment']}
        for week, block in groups:
            block_rows = [row['assigned'] for row in self.tables['assignment']
                if (row['week'],row['block'])==(week,block)]
            self.assertEqual(sorted(block_rows), [False,True])
        cancelled = [row for row in self.tables['windows'] if row['room']=='2D']
        self.assertIn('cancelled', {row['state'] for row in cancelled})
        self.assertGreater(cancelled[-1]['close_day'], cancelled[0]['close_day'])
