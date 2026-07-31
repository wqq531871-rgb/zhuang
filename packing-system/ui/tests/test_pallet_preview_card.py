import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets

from realtime_dashboard_v2 import PalletPreviewCard


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_preview_card_displays_full_box_unique_id_below_pallet_id():
    card = PalletPreviewCard()
    uid = "9827a6fe82ef46258f298c90f342c732"

    card.set_data(
        {
            "pallet_id": "MH423C-PAIN26316EN01S-1",
            "box_unique_id": uid,
            "packed_items": [],
        }
    )

    assert card.title.text() == "MH423C-PAIN26316EN01S-1"
    assert card.box_unique_id.text() == f"box_unique_id：{uid}"


def test_preview_card_identifiers_can_be_selected_and_copied():
    card = PalletPreviewCard()

    assert card.title.textInteractionFlags() & QtCore.Qt.TextSelectableByMouse
    assert (
        card.box_unique_id.textInteractionFlags()
        & QtCore.Qt.TextSelectableByMouse
    )
