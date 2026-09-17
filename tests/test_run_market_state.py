import unittest
from datetime import date

from scripts.run_market_state import parse_boc_selected_bonds_html


class MarketStateEntrypointTests(unittest.TestCase):
    def test_boc_selected_bonds_parser(self):
        html = '''
        <table>
          <tr><th>Series</th><th>2026-09-10</th><th>2026-09-11</th><th>2026-09-14</th><th>2026-09-15</th><th>2026-09-16</th></tr>
          <tr><th>2 year</th><td>3.31</td><td>3.35</td><td>3.37</td><td>3.35</td><td>3.35</td></tr>
          <tr><th>5 year</th><td>3.63</td><td>3.65</td><td>3.65</td><td>3.65</td><td>3.64</td></tr>
          <tr><th>10 year</th><td>3.94</td><td>3.95</td><td>3.94</td><td>3.95</td><td>3.92</td></tr>
          <tr><th>Long-term</th><td>4.28</td><td>4.28</td><td>4.27</td><td>4.29</td><td>4.25</td></tr>
        </table>
        '''
        result = parse_boc_selected_bonds_html(html, date(2026, 9, 1), date(2026, 9, 17))
        self.assertEqual(result["2Y"][date(2026, 9, 16)], 3.35)
        self.assertEqual(result["5Y"][date(2026, 9, 16)], 3.64)
        self.assertEqual(result["10Y"][date(2026, 9, 16)], 3.92)
        self.assertEqual(result["LONG"][date(2026, 9, 16)], 4.25)


if __name__ == "__main__":
    unittest.main()
