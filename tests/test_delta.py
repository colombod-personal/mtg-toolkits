import csv

import pytest

from mtg_toolkits import delta
from mtg_toolkits.models import CollectionEntry as E
from mtg_toolkits.models import Condition, Finish


def snapshot_old():
    return [
        E("Sol Ring", 2, set_code="C21", collector_number="263", folder="Binder A"),
        E("Lightning Bolt", 4, set_code="M11", collector_number="149"),
        E("Delver of Secrets", 1, set_code="ISD", collector_number="051", finish=Finish.FOIL, scryfall_id="delver-id"),
        E("Counterspell", 1, set_code="MH2", collector_number="267"),
    ]


def snapshot_new():
    return [
        E("Sol Ring", 1, set_code="c21", collector_number="263", folder="Binder A"),
        E("Sol Ring", 2, set_code="C21", collector_number="263", folder="Binder B"),  # split stack
        E("Lightning Bolt", 3, set_code="M11", collector_number="149"),
        E("Delver of Secrets // Insectile Aberration", 1, set_code="isd", collector_number="51", finish=Finish.FOIL),
        E("Brainstorm", 4, set_code="ICE", collector_number="61"),
    ]


def test_diff_statuses_and_normalisation():
    d = delta.diff(snapshot_old(), snapshot_new())
    status = {line.entry.name.split(" // ")[0]: (line.status, line.delta) for line in d.lines}
    assert status == {
        "Brainstorm": ("added", 4),
        "Sol Ring": ("increased", 1),
        "Lightning Bolt": ("decreased", -1),
        "Counterspell": ("removed", -1),
        "Delver of Secrets": ("unchanged", 0),  # DFC name, case and leading zero all normalised
    }
    assert d.summary() == {"added": 1, "removed": 1, "increased": 1, "decreased": 1, "unchanged": 1,
                           "copies_in": 5, "copies_out": 2}
    assert [line.status for line in d.lines] == ["added", "increased", "decreased", "removed", "unchanged"]
    assert d.unchanged[0].entry.scryfall_id == "delver-id"  # carried over from the old side


def test_gains_and_losses_are_ready_to_write():
    d = delta.diff(snapshot_old(), snapshot_new())
    assert sorted((e.name, e.quantity) for e in d.gains()) == [("Brainstorm", 4), ("Sol Ring", 1)]
    assert sorted((e.name, e.quantity) for e in d.losses()) == [("Counterspell", 1), ("Lightning Bolt", 1)]


def test_folders_make_moves_visible():
    d = delta.diff(snapshot_old(), snapshot_new(), folders=True)
    sol = {line.entry.folder: (line.status, line.delta) for line in d.lines if line.entry.name == "Sol Ring"}
    assert sol == {"Binder A": ("decreased", -1), "Binder B": ("added", 2)}


def test_match_granularity():
    old = [E("Island", 10, set_code="UNH", collector_number="136", condition=Condition.PLAYED)]
    new = [E("Island", 10, set_code="DMU", collector_number="262")]
    assert not delta.diff(old, new, delta.BY_CARD)
    assert delta.diff(old, new, delta.BY_PRINTING).summary()["added"] == 1
    assert delta.diff(old, [E("Island", 10, set_code="UNH", collector_number="136")], delta.BY_COPY)
    with pytest.raises(ValueError):
        delta.diff(old, new, ("colour",))


@pytest.mark.parametrize("folders", [False, True])
def test_apply_reproduces_new(folders):
    old, new = snapshot_old(), snapshot_new()
    d = delta.diff(old, new, folders=folders)
    got = delta.aggregate(d.apply(old), folders=folders)
    want = delta.aggregate(new, folders=folders)
    assert {k: v.quantity for k, v in got.items()} == {k: v.quantity for k, v in want.items()}


def test_shortfall_against_deck():
    deck = [E("Sol Ring", 1), E("Counterspell", 1), E("Rhystic Study", 1)]
    owned = [E("Sol Ring", 3, set_code="C21", collector_number="263"), E("Counterspell", 1, set_code="MH2")]
    assert [(e.name, e.quantity) for e in delta.shortfall(deck, owned)] == [("Rhystic Study", 1)]


def test_write_csv(tmp_path):
    out = tmp_path / "changes.csv"
    assert delta.write_csv(delta.diff(snapshot_old(), snapshot_new()), out) == 4
    rows = list(csv.DictReader(out.open()))
    assert (rows[0]["Change"], rows[0]["Delta"], rows[0]["Name"]) == ("added", "+4", "Brainstorm")


def test_folder_in_by_is_honoured():
    old = [E("Sol Ring", 1, set_code="C21", collector_number="263", folder="x")]
    new = [E("Sol Ring", 1, set_code="C21", collector_number="263", folder="y")]
    d = delta.diff(old, new, delta.BY_PRINTING + ("folder",))
    assert d.summary()["added"] == 1 and d.summary()["removed"] == 1
    assert [e.folder for e in d.apply(old)] == ["y"]
