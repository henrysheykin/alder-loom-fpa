import unittest
from datetime import date
from core import cents, split_cents, nights, Dataset

class EconomicsTests(unittest.TestCase):
    def test_half_up_and_allocation_conserve_cents(self):
        self.assertEqual(cents('1.005'), 101)
        self.assertEqual(split_cents(10001, [60,52,44]), [3846,3334,2821])
        self.assertEqual(sum(split_cents(-10001,[60,52,44])), -10001)
    def test_checkout_exclusive_cutoff(self):
        self.assertEqual(list(nights(date(2026,10,30),date(2026,11,3),date(2026,10,31))),[date(2026,10,30),date(2026,10,31)])
    def test_journal_rejects_imbalance(self):
        ds=Dataset()
        with self.assertRaises(ValueError):
            ds.post('2026-10-31','test','fixture','X',[('CORP','1000',100),('CORP','3000',-99)])
        self.assertFalse(ds.tables['quickbooks/general_ledger'])

if __name__=='__main__': unittest.main()
