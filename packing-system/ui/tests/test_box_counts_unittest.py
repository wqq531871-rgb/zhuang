import unittest

from dashboard_state import regular_irregular_box_counts


class BoxCountTests(unittest.TestCase):
    def test_counts_integer_multiple_specs_across_pallets(self):
        pallets = [
            {
                "packed_items": [
                    {"original_length": 100, "original_width": 80, "original_height": 50},
                    {"original_length": 100, "original_width": 80, "original_height": 50},
                ]
            },
            {
                "packed_items": [
                    {"original_length": 200, "original_width": 160, "original_height": 100},
                    {"original_length": 150, "original_width": 120, "original_height": 80},
                    {"original_length": 150, "original_width": 120, "original_height": 80},
                ]
            },
        ]

        self.assertEqual(regular_irregular_box_counts(pallets), (3, 2))

    def test_prefers_original_dimensions_over_gap_dimensions(self):
        pallets = [
            {
                "packed_items": [
                    {
                        "length": 102,
                        "width": 82,
                        "height": 50,
                        "original_length": 100,
                        "original_width": 80,
                        "original_height": 50,
                    },
                    {
                        "length": 202,
                        "width": 162,
                        "height": 100,
                        "original_length": 200,
                        "original_width": 160,
                        "original_height": 100,
                    },
                ]
            }
        ]

        self.assertEqual(regular_irregular_box_counts(pallets), (2, 0))

    def test_treats_invalid_and_unmatched_boxes_as_irregular(self):
        pallets = [
            {
                "packed_items": [
                    {"raw_length": 100, "raw_width": 80, "raw_height": 50},
                    {"length": 0, "width": 80, "height": 50},
                    {"length": "bad", "width": 80, "height": 50},
                ]
            }
        ]

        self.assertEqual(regular_irregular_box_counts(pallets), (0, 3))

    def test_accepts_small_float_rounding_noise(self):
        pallets = [
            {
                "packed_items": [
                    {"length": 100, "width": 80, "height": 50},
                    {"length": 200.00000001, "width": 160, "height": 100},
                ]
            }
        ]

        self.assertEqual(regular_irregular_box_counts(pallets), (2, 0))


if __name__ == "__main__":
    unittest.main()
