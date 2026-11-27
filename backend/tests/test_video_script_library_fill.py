"""旧文案补写标题和正文：一次小调用、同样的校验、存为同一条的新版本、失败不扣费."""

import json
from uuid import uuid4

import pytest

from tests.test_video_credit_billing import billing, holds, prices, set_balance  # noqa: F401
from tests.test_video_generation import video_gen  # noqa: F401

SCRIPT = (
    "冬天手干怎么办？我做了6年美甲，店里一直用小熊暖暖护手霜。"
    "质地清爽不黏腻，吸收快，抹完就能玩手机。"
)
GOOD = {
    "publish_title": "冬天手干？美甲师店里常备的护手霜",
    "publish_body": (
        "做了6年美甲，店里一直用这支，清爽不黏腻，吸收快。\n"
        "#护手霜 #冬季护手 #美甲师日常"
    ),
}


class FakePlanner:
    def __init__(self, settings, answers):
        self.settings, self.answers, self.calls = settings, list(answers), []

    def request(self, *_args, **kwargs):
        self.calls.append(kwargs["json"]["messages"])
        answer = self.answers.pop(0)
        return {
            "id": f"fake-{len(self.calls)}",
            "choices": [
                {"message": {"content": json.dumps(answer, ensure_ascii=False)}}
            ],
        }


@pytest.fixture
def fill(billing):  # noqa: F811
    client, *_rest, workspace = billing
    settings = client.app.state.settings
    settings.video_script_planning_enabled = True
    prices(client, writing_publish_fill=2)
    set_balance(client, workspace, 1000)
    root = f"/api/v1/video-studio/workspaces/{workspace}"
    entry = client.post(
        f"{root}/script-library",
        json={"request_id": str(uuid4()), "script": SCRIPT},
    ).json()
    assert entry["publish_title"] == "" and entry["revision"] == 1

    def run(answers, platform="xiaohongshu", request_id=None):
        fake = FakePlanner(settings, answers)
        client.app.state.video_assistance_provider = fake
        started = client.post(
            f"{root}/script-library/{entry['id']}/publish-fill",
            json={"request_id": request_id or str(uuid4()), "platform": platform},
        )
        assert started.status_code == 200, started.text
        task = started.json()["task_id"]
        status = client.get(
            f"{root}/script-library/{entry['id']}/publish-fill/{task}"
        ).json()
        return status, fake

    return client, root, entry, run


def test_an_old_entry_gets_title_and_body_as_a_new_version_and_is_charged_once(fill):
    client, root, entry, run = fill
    status, fake = run([GOOD])
    assert status["status"] == "completed", status
    assert len(fake.calls) == 1  # one small call
    filled = status["entry"]
    assert filled["id"] == entry["id"] and filled["revision"] == 2
    assert filled["publish_title"] == GOOD["publish_title"]
    assert "#美甲师日常" in filled["publish_body"]
    assert filled["script"] == SCRIPT and filled["platform"] == "xiaohongshu"
    assert holds(client, status["task_id"]) == [("writing_publish_fill", "settled", 2)]
    rules = json.loads(fake.calls[0][1]["content"])["rules"]
    assert any("口播稿里已经说过" in rule for rule in rules)
    assert client.get(f"{root}/script-library").json()["total"] == 1


def test_the_same_checks_correct_a_long_title_once(fill):
    _client, _root, _entry, run = fill
    long_title = {
        **GOOD,
        "publish_title": "冬天手干到起皮的姐妹一定要试试这支美甲师店里常备的护手霜",
    }
    status, fake = run([long_title, GOOD])
    assert status["status"] == "completed"
    assert len(fake.calls) == 2
    assert "最多20个字" in fake.calls[1][-1]["content"]


@pytest.mark.parametrize(
    "bad",
    [
        {
            **GOOD,
            "publish_body": "只要39元，清爽不黏腻。#护手霜 #冬季护手 #好物",
        },  # 口播稿没有的价格
        {
            **GOOD,
            "publish_body": "清爽不黏腻，吸收快。#护手霜 #平价好物 #冬季护手",
        },  # 没依据的平价
        {**GOOD, "publish_body": "清爽不黏腻，吸收快。#护手霜"},  # 标签不够
    ],
)
def test_a_failed_fill_changes_nothing_and_is_not_charged(fill, bad):
    client, root, entry, run = fill
    status, fake = run([bad, bad])
    assert status["status"] == "failed" and "没有扣积分" in status["message"]
    assert len(fake.calls) == 2
    after = client.get(f"{root}/script-library/{entry['id']}").json()
    assert after["revision"] == 1 and after["publish_title"] == ""
    assert holds(client, status["task_id"]) == [("writing_publish_fill", "released", 0)]


def test_a_repeated_request_is_not_sent_again(fill):
    _client, _root, _entry, run = fill
    request_id = str(uuid4())
    first, fake = run([GOOD], request_id=request_id)
    again, fake2 = run([GOOD], request_id=request_id)
    assert again["task_id"] == first["task_id"] and not fake2.calls
