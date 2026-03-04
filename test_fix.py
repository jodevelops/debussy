#!/usr/bin/env python3
"""Quick test to verify the ingest_csv fix."""
import sys
import unittest
sys.path.insert(0, 'src')

from tests.test_core import TestIngest, TestAnalysis

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestIngest))
    suite.addTests(loader.loadTestsFromTestCase(TestAnalysis))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    sys.exit(0 if result.wasSuccessful() else 1)
