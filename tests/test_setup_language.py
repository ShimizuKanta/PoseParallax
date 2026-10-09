import re
from server.setup_page import setup_html


def test_setup_language_keeps_urls_and_fingerprint():
    for language, label in [('ja', 'ゲームを開く'), ('en', 'Open game')]:
        page = setup_html('https://192.0.2.40:8443/', 'AB:CD:EF', language).decode()
        assert f'lang="{language}"' in page
        assert label in page
        assert 'href="https://192.0.2.40:8443/"' in page
        assert 'AB:CD:EF' in page
        assert '/pose-parallax-ca.cer' in page
        if language == 'en':
            assert not re.search(r'[一-龯ぁ-んァ-ン]', page.replace('日本語', ''))
