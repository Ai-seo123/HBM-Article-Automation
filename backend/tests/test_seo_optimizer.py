import unittest
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.seo_optimizer import (
    to_title_case,
    format_headings_title_case,
    optimize_introduction,
    optimize_subheadings,
    optimize_keyphrase_density,
    inject_internal_links,
    inject_external_authority_links,
)

class TestSEOOptimizer(unittest.TestCase):
    def test_to_title_case(self):
        self.assertEqual(to_title_case("running a business from home"), "Running a Business from Home")
        self.assertEqual(to_title_case("1. establish dedicated working hours"), "1. Establish Dedicated Working Hours")

    def test_format_headings_title_case(self):
        html = "<h2>running a business from home</h2><p>text</p><h3>evaluate financial workflows</h3>"
        opt, changes = format_headings_title_case(html)
        self.assertIn("Running a Business from Home", opt)
        self.assertIn("Evaluate Financial Workflows", opt)
        self.assertEqual(len(changes), 2)

    def test_optimize_introduction(self):
        html = "<p>For Canadian SMBs, the consequences of a poor hiring decision can be particularly significant.</p>"
        opt, changed = optimize_introduction(html, "Reduce Hiring Risk")
        self.assertTrue(changed)
        self.assertIn("reduce hiring risk", opt.lower())

    def test_optimize_subheadings(self):
        html = "<h2>Identify Daily Operational Delays</h2><p>text</p><h2>Let Routine Work Take Care of Itself</h2>"
        opt, changes = optimize_subheadings(html, "Improve Office Efficiency")
        self.assertTrue(len(changes) > 0)
        self.assertIn("improve office efficiency", opt.lower())

    def test_optimize_keyphrase_density(self):
        html = "<p>Intro paragraph without keyphrase.</p><p>Second paragraph explaining important business details that will help owners succeed.</p><p>Third paragraph with more insights into operational workflows and systems.</p>"
        opt, count = optimize_keyphrase_density(html, "Remote Entrepreneur", min_required=2)
        self.assertGreaterEqual(count, 2)
        self.assertIn("remote entrepreneur", opt.lower())

    def test_inject_internal_links_normalizes_www(self):
        html = "<p>Visit our website at <a href='https://www.homebusinessmag.com/management/'>HBM link</a> for more details.</p>"
        opt, added = inject_internal_links(html, "Some Keyphrase")
        # Ensure www is stripped while preserving quote style
        self.assertIn("href='https://homebusinessmag.com/management/'", opt)
        # Should have added at least 1 more to reach 2
        total_hbm = opt.count("homebusinessmag.com")
        self.assertGreaterEqual(total_hbm, 2)

    def test_inject_external_authority_links(self):
        html = "<p>Developing a strong business strategy helps teams stay ahead of competition.</p>"
        opt, added = inject_external_authority_links(html, "Some Keyphrase")
        self.assertTrue(any(domain in opt for domain in ["entrepreneur.com", "forbes.com"]))

if __name__ == "__main__":
    unittest.main()
