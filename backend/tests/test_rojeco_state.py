"""get_device_state của máy cho ăn: map online + DP thật -> trạng thái app.

Không gọi mạng: thay `openapi` bằng stub trả JSON đúng shape Tuya Cloud.
"""
import asyncio

from app.services.rojeco_connector import RojecoConnector

DEV = "a32e6ab42d076b8bb5bbrh"


class _StubApi:
    def __init__(self, online=True, dps=None, info_ok=True, status_ok=True, raises=False):
        self.online, self.dps = online, dps or {}
        self.info_ok, self.status_ok, self.raises = info_ok, status_ok, raises

    def connect(self):
        return {"success": True}

    def get(self, path):
        if self.raises:
            raise ConnectionError("mạng chết")
        if path.endswith("/status"):
            return {
                "success": self.status_ok,
                "result": [{"code": k, "value": v} for k, v in self.dps.items()],
            }
        return {"success": self.info_ok, "result": {"online": self.online}}


def _state(api):
    c = RojecoConnector()
    c.is_connected = True
    c.openapi = api
    return asyncio.run(c.get_device_state(DEV))


def test_online_doc_dung_dp_that():
    s = _state(_StubApi(dps={"feed_state": "standby", "feed_report": 2, "manual_feed": 1}))
    assert s == {"device_id": DEV, "status": "ON", "feed_state": "standby", "last_feed": 2}


def test_dang_nha_hat():
    assert _state(_StubApi(dps={"feed_state": "feeding"}))["feed_state"] == "feeding"


def test_thiet_bi_offline():
    assert _state(_StubApi(online=False, dps={"feed_state": "standby"}))["status"] == "offline"


def test_cloud_tu_choi_thi_offline():
    assert _state(_StubApi(info_ok=False))["status"] == "offline"
    assert _state(_StubApi(status_ok=False))["status"] == "offline"


def test_loi_mang_khong_nem_exception():
    assert _state(_StubApi(raises=True)) == {"device_id": DEV, "status": "offline"}


def test_dp_thieu_hoac_la():
    s = _state(_StubApi(dps={"feed_state": "weird", "feed_report": "x"}))
    assert s["status"] == "ON"
    assert s["feed_state"] == "unknown"
    assert s["last_feed"] is None
