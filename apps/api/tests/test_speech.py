from app.speech import clean_preview


def test_preview_skips_whispers_caption_notes_without_dropping_spoken_requests():
    assert clean_preview('(字幕君)') == ''
    assert clean_preview('（音乐）\n你好，我想咨询劳动合同。') == '你好，我想咨询劳动合同。'
    assert clean_preview('我遇到的问题（工资）需要登记。') == '我遇到的问题（工资）需要登记。'
