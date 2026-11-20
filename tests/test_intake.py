from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import create_app

BATCH = "BL-1120-21"


def ticket(number, lot, gross, tare):
    return {"ticket": number, "lot": lot, "gross": gross, "tare": tare, "unit": "kg"}


def moisture(lot):
    return [
        {
            "lot": lot,
            "sample": f"{lot}-上层",
            "position": "上层",
            "mass": 100,
            "mass_unit": "g",
            "water": "4",
            "unit": "%",
        },
        {
            "lot": lot,
            "sample": f"{lot}-下层",
            "position": "下层",
            "mass": 300,
            "mass_unit": "g",
            "water": "8",
            "unit": "%",
        },
    ]


def grade(lot, color="白", impurity="0.5"):
    return {
        "lot": lot,
        "color": color,
        "offcolor": "1.0",
        "impurity": impurity,
        "unit": "%",
    }


def target(mass=500):
    return {
        "target": "车 01｜清白料",
        "colors": ["白料"],
        "grades": ["A", "B"],
        "mass": mass,
        "unit": "kg",
        "max_impurity": "1.0",
        "impurity_unit": "%",
        "priority": 1,
    }


def tickets_l01():
    return [
        ticket("01001", "L01", 530, 205),
        ticket("01002", "L01", 540, 210),
        ticket("01003", "L01", 550, 215),
    ]


def tickets_l02():
    return [ticket("02001", "L02", 535, 205), ticket("02002", "L02", 545, 210)]


def post(client, payload, batch=BATCH):
    return client.post(f"/api/batches/{batch}/intakes", json=payload)


def ledger(client, batch=BATCH):
    return client.get(f"/api/batches/{batch}/ledger")


def full_l01(**extra):
    return {
        "tickets": tickets_l01(),
        "moisture": moisture("L01"),
        "grades": [grade("L01")],
        **extra,
    }


def test_partial_arrival_loadable_only_after_lab_complete(client):
    first = post(client, {"tickets": tickets_l01(), "targets": [target()]}).json()
    lot = first["ledger"]["lots"][0]
    assert (
        lot["arrived_wet_g"],
        lot["provisional_dry_g"],
        lot["pending_wet_g"],
    ) == (990000, 0, 990000)
    assert first["ledger"]["targets"][0]["short_g"] == 500000
    assert first["ledger"]["official_remaining_g"] is None

    second = post(
        client, {"moisture": moisture("L01"), "grades": [grade("L01")]}
    ).json()
    lot = second["ledger"]["lots"][0]
    assert (lot["provisional_dry_g"], lot["pending_wet_g"]) == (920700, 0)
    assert (lot["allocated_dry_g"], lot["remaining_g"]) == (500000, 420700)
    assert lot["intakes"] == [1, 2]
    delta = second["ledger"]["intakes"][1]["delta"]
    assert delta["provisional_dry_g"] == 920700
    assert delta["pending_wet_g"] == -990000


def test_official_remaining_waits_for_close_and_publish(client):
    post(client, full_l01(targets=[target()]))
    state = ledger(client).json()
    assert state["complete"] is False and state["official_remaining_g"] is None
    refused = client.post(f"/api/batches/{BATCH}/publish")
    assert refused.status_code == 409
    assert refused.json()["code"] == "INCOMPLETE_BATCH"

    post(client, {"closed": True})
    state = ledger(client).json()
    assert state["complete"] is True and state["official_remaining_g"] == 420700
    snapshot = client.post(f"/api/batches/{BATCH}/publish").json()
    assert snapshot["seq"] == 2
    assert snapshot["ledger"]["official_remaining_g"] == 420700
    again = client.post(f"/api/batches/{BATCH}/publish").json()
    assert again["id"] == snapshot["id"]
    assert ledger(client).json()["published"]["stale"] is False


def test_repeat_intake_adds_no_receiving(client):
    payload = full_l01()
    first = post(client, payload).json()
    second = post(client, payload).json()
    assert first["reused"] is False and second["reused"] is True
    assert second["intake"] == first["intake"]
    state = second["ledger"]
    assert len(state["intakes"]) == 1
    assert state["totals"]["arrived_wet_g"] == 990000


def test_concurrent_repeat_intake_is_idempotent(client):
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: post(client, full_l01()).json(), range(4))
        )
    assert sum(row["reused"] for row in results) == 3
    assert len({row["intake"]["id"] for row in results}) == 1
    assert ledger(client).json()["totals"]["arrived_wet_g"] == 990000


def test_concurrent_distinct_intakes_are_all_kept(client):
    def send(index):
        payload = {
            "tickets": [ticket(f"0900{index}", "L09", 500 + index, 200)]
        }
        return post(client, payload).json()

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(send, range(1, 7)))
    assert not any(row["reused"] for row in results)
    state = ledger(client).json()
    assert [row["seq"] for row in state["intakes"]] == [1, 2, 3, 4, 5, 6]
    assert state["totals"]["arrived_wet_g"] == sum(
        (500 + index - 200) * 1000 for index in range(1, 7)
    )


def test_overlapping_tickets_merged_once(client):
    post(client, {"tickets": tickets_l01()[:2]})
    state = post(client, {"tickets": tickets_l01()[1:]}).json()["ledger"]
    assert len(state["intakes"]) == 2
    assert state["totals"]["arrived_wet_g"] == 990000
    assert state["isolated"] == 0


def test_conflicting_reticket_isolated_and_blocks_publish(client):
    post(client, full_l01(closed=True))
    assert ledger(client).json()["complete"] is True
    late = post(client, {"tickets": [ticket("01001", "L01", 531, 205)]}).json()[
        "ledger"
    ]
    assert late["isolated"] == 2
    assert late["totals"]["arrived_wet_g"] == 665000
    assert late["intakes"][1]["delta"]["arrived_wet_g"] == -325000
    assert late["complete"] is False
    assert client.post(f"/api/batches/{BATCH}/publish").status_code == 409


def test_failed_publish_keeps_previous_publication(client):
    post(client, full_l01(targets=[target()], closed=True))
    snapshot = client.post(f"/api/batches/{BATCH}/publish").json()
    assert snapshot["ledger"]["official_remaining_g"] == 420700

    post(client, {"tickets": tickets_l02()})
    assert client.post(f"/api/batches/{BATCH}/publish").status_code == 409
    kept = client.get(f"/api/batches/{BATCH}/publication").json()
    assert kept["id"] == snapshot["id"] and kept["seq"] == 1
    assert kept["ledger"]["official_remaining_g"] == 420700
    state = ledger(client).json()
    assert state["published"]["stale"] is True
    assert state["official_remaining_g"] is None


def test_late_evidence_not_lost_and_republish(client):
    post(client, full_l01(targets=[target()], closed=True))
    client.post(f"/api/batches/{BATCH}/publish")
    post(client, {"tickets": tickets_l02()})
    state = post(
        client, {"moisture": moisture("L02"), "grades": [grade("L02")]}
    ).json()["ledger"]
    lots = {row["lot"]: row for row in state["lots"]}
    assert lots["L02"]["intakes"] == [2, 3]
    assert lots["L02"]["provisional_dry_g"] == 618450
    assert state["complete"] is True
    snapshot = client.post(f"/api/batches/{BATCH}/publish").json()
    assert snapshot["seq"] == 3
    assert snapshot["ledger"]["official_remaining_g"] == 420700 + 618450


def test_unarrived_never_consumed(client):
    state = post(client, {"targets": [target(2000)]}).json()["ledger"]
    assert state["totals"]["allocated_dry_g"] == 0
    assert state["targets"][0]["short_g"] == 2000000

    state = post(client, {"tickets": tickets_l01()}).json()["ledger"]
    assert state["totals"]["allocated_dry_g"] == 0
    assert state["totals"]["pending_wet_g"] == 990000

    state = post(
        client, {"moisture": moisture("L01"), "grades": [grade("L01")]}
    ).json()["ledger"]
    totals = state["totals"]
    assert totals["allocated_dry_g"] == 920700
    assert (
        totals["allocated_dry_g"] + totals["remaining_g"]
        == totals["provisional_dry_g"]
    )
    assert state["targets"][0]["short_g"] == 2000000 - 920700


def test_intake_validation(client):
    assert post(client, []).json()["code"] == "BAD_INTAKE"
    assert post(client, {}).json()["code"] == "EMPTY_INTAKE"
    assert post(client, {"closed": "是"}).json()["code"] == "BAD_INTAKE"
    assert post(client, {"tickets": {}}).json()["code"] == "BAD_SECTION"
    mismatch = post(client, {"batch": "BL-OTHER", "closed": True})
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "BATCH_MISMATCH"
    bad = client.post(f"/api/batches/{BATCH}/intakes", content="坏").json()
    assert bad["code"] == "BAD_JSON"
    assert ledger(client).status_code == 404


def test_unknown_batch_is_404(client):
    assert client.get("/api/batches/BL-X/ledger").json()["code"] == "BATCH_NOT_FOUND"
    assert (
        client.get("/api/batches/BL-X/publication").json()["code"]
        == "PUBLICATION_NOT_FOUND"
    )
    assert client.post("/api/batches/BL-X/publish").json()["code"] == "BATCH_NOT_FOUND"


def test_ledger_and_publication_persist(tmp_path):
    file = tmp_path / "state.sqlite3"
    with TestClient(create_app(file)) as client:
        post(client, full_l01(closed=True))
        snapshot = client.post(f"/api/batches/{BATCH}/publish").json()
    with TestClient(create_app(file)) as client:
        state = ledger(client).json()
        assert state["complete"] is True
        assert state["official_remaining_g"] == 920700
        kept = client.get(f"/api/batches/{BATCH}/publication").json()
        assert kept["id"] == snapshot["id"]


def test_workbench_has_intake_panel(client):
    assert "批次接收台账" in client.get("/").text
