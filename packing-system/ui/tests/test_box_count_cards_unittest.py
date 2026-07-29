import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from realtime_dashboard_v2 import IndustrialPackingWorkbench


class BoxCountCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_right_summary_cards_show_global_regular_and_irregular_counts(self):
        with TemporaryDirectory() as temp_dir:
            window = IndustrialPackingWorkbench(Path(temp_dir))
            self.addCleanup(window.close)

            self.assertEqual(window.card_regular_boxes.title_label.text(), "规则箱子数目")
            self.assertEqual(window.card_irregular_boxes.title_label.text(), "不规则箱子数目")

            window.show()
            self.app.processEvents()
            self.assertEqual(
                window.card_regular_boxes.y(),
                window.card_irregular_boxes.y(),
            )
            self.assertLess(
                window.card_regular_boxes.x(),
                window.card_irregular_boxes.x(),
            )
            self.assertLess(window.card_regular_boxes.y(), window.card_fill.y())
            self.assertLess(window.card_irregular_boxes.y(), window.card_mpm.y())

            window.pallets = [
                {
                    "packed_items": [
                        {"original_length": 100, "original_width": 80, "original_height": 50},
                        {"original_length": 200, "original_width": 160, "original_height": 100},
                        {"original_length": 150, "original_width": 120, "original_height": 80},
                    ]
                }
            ]
            window._update_box_count_cards()

            self.assertEqual(window.card_regular_boxes.value_label.text(), "2")
            self.assertEqual(window.card_irregular_boxes.value_label.text(), "1")

            window.clear_current_views()
            self.assertEqual(window.card_regular_boxes.value_label.text(), "--")
            self.assertEqual(window.card_irregular_boxes.value_label.text(), "--")


if __name__ == "__main__":
    unittest.main()
