"""Owner tools: conversations list, insights, CSV/Excel export."""

import csv
import io
import zipfile

from conftest import ask


def setup_chats(client, admin, embed, fakes):
    origin = f"https://{embed['site']['domain']}"
    ask(client, embed["key"], "What do you sell?", visitor="visitorINSIGHTS0000001", origin=origin)
    fakes.answer = "NOT_FOUND"
    ask(client, embed["key"], "What is the airspeed of a swallow?", visitor="visitorINSIGHTS0000002", origin=origin)
    ask(client, embed["key"], '=HYPERLINK("http://evil.example","x")', visitor="visitorINSIGHTS0000003", origin=origin)
    admin.post(f"/api/public/{embed['key']}/messages", headers={"Sec-Fetch-Site": "same-origin"},
               json={"visitor_id": "previewVisitor00000099", "content": "hi", "preview": True})


def rows_of(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_chat_list_flags(client, admin, embed, fakes):
    setup_chats(client, admin, embed, fakes)
    chats = admin.get(f"/api/embeds/{embed['id']}/chats").json()
    assert sum(c["is_test"] for c in chats) == 1
    assert sum(c["unanswered"] > 0 for c in chats if not c["is_test"]) == 2


def test_insights(client, admin, embed, fakes):
    setup_chats(client, admin, embed, fakes)
    ins = admin.get(f"/api/embeds/{embed['id']}/insights").json()
    assert len(ins["days"]) == 30 and ins["days"][-1]["chats"] == 3
    assert any("sell" in q["question"] for q in ins["top_questions"])
    assert any("swallow" in q["question"] for q in ins["unanswered"])
    assert all(q["question"] != "hi" for q in ins["top_questions"])


def test_csv_export_with_filters_and_formula_protection(client, admin, embed, fakes):
    setup_chats(client, admin, embed, fakes)
    rows = rows_of(admin.get(f"/api/embeds/{embed['id']}/export", params={"format": "csv"}))
    assert rows[0][0] == "Conversation" and len(rows) == 7
    assert all(r[3] != "yes" for r in rows[1:])
    assert any(r[6].startswith("'=HYPERLINK") for r in rows[1:])
    with_tests = rows_of(admin.get(f"/api/embeds/{embed['id']}/export", params={"format": "csv", "tests": "true"}))
    assert any(r[3] == "yes" for r in with_tests[1:])
    missed = rows_of(admin.get(f"/api/embeds/{embed['id']}/export", params={"format": "csv", "unanswered": "true"}))
    convs = {r[0] for r in missed[1:]}
    assert len(convs) == 2 and all(any(r[0] == c and r[7] == "no" for r in missed[1:]) for c in convs)
    assert len(rows_of(admin.get(f"/api/embeds/{embed['id']}/export", params={"format": "csv", "start": "2099-01-01"}))) == 1
    assert admin.get(f"/api/embeds/{embed['id']}/export", params={"start": "yesterday"}).status_code == 400


def test_excel_export(client, admin, embed, fakes):
    setup_chats(client, admin, embed, fakes)
    r = admin.get(f"/api/embeds/{embed['id']}/export", params={"format": "xlsx"})
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats") and 'filename="' in r.headers["content-disposition"]
    sheet = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "swallow" in sheet


def test_owner_only(member, embed):
    for path in ("chats", "insights", "export"):
        assert member.get(f"/api/embeds/{embed['id']}/{path}").status_code == 404
